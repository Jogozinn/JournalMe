#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.NinjaScript;
#endregion

// JournalMe read-only NinjaTrader desktop bridge.
// Data flow is one-way: NinjaTrader -> JournalMe. This AddOn contains no code
// that submits, changes, cancels, or flattens orders.
namespace NinjaTrader.NinjaScript.AddOns
{
    public class JournalMeBridge : AddOnBase
    {
        private const string BridgeVersion = "0.7.1";
        private readonly HashSet<Account> subscribedAccounts = new HashSet<Account>();
        private readonly object queueLock = new object();
        private readonly object snapshotLock = new object();
        private Timer heartbeatTimer;
        private bool started;
        private BridgeConfig config;
        private DateTime lastSnapshotSentUtc = DateTime.MinValue;
        private string lastSnapshotFingerprint = "";

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "JournalMeBridge";
                Description = "Read-only JournalMe live execution bridge";
            }
            else if (State == State.Terminated)
            {
                StopBridge();
            }
        }

        protected override void OnWindowCreated(Window window)
        {
            if (!(window is ControlCenter) || started)
                return;

            config = BridgeConfig.Load();
            if (!config.IsConfigured)
            {
                Write("CONFIG_REQUIRED|Create " + BridgeConfig.ConfigPath + " from JournalMe Settings > Broker connections");
                return;
            }

            started = true;
            Account.AccountStatusUpdate += OnAccountStatusUpdate;
            SubscribeExistingAccounts();
            heartbeatTimer = new Timer(_ => Task.Run(() => Heartbeat()), null, TimeSpan.Zero, TimeSpan.FromSeconds(60));
            Write("READY|version=" + BridgeVersion + "|account=" + config.AccountName + "|api=" + config.ApiBase);
        }

        protected override void OnWindowDestroyed(Window window)
        {
            if (window is ControlCenter)
                StopBridge();
        }

        private void SubscribeExistingAccounts()
        {
            List<Account> snapshot;
            lock (Account.All)
                snapshot = Account.All.ToList();
            foreach (Account account in snapshot)
                SubscribeAccount(account);
        }

        private void SubscribeAccount(Account account)
        {
            if (account == null || subscribedAccounts.Contains(account))
                return;
            if (!string.Equals(account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                return;

            account.ExecutionUpdate += OnExecutionUpdate;
            account.AccountItemUpdate += OnAccountItemUpdate;
            subscribedAccounts.Add(account);
            string connection = account.Connection != null && account.Connection.Options != null
                ? account.Connection.Options.Name
                : "none";
            Write("ACCOUNT|name=" + account.Name + "|connection=" + connection + "|readOnly=true");
            Task.Run(() => SendAccountSnapshot(account, true));
        }

        private void OnAccountStatusUpdate(object sender, AccountStatusEventArgs e)
        {
            if (e == null || e.Account == null)
                return;
            SubscribeAccount(e.Account);
            if (string.Equals(e.Account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                Write("ACCOUNT_STATUS|name=" + e.Account.Name + "|status=" + e.Status);
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            if (e == null || e.Execution == null || e.Execution.Account == null)
                return;
            if (!string.Equals(e.Execution.Account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                return;

            Execution execution = e.Execution;
            string side = NormalizeSide(execution);
            if (side == null)
            {
                Write("SKIP|unsupported order action for execution=" + execution.ExecutionId);
                return;
            }

            string executionId = execution.ExecutionId;
            if (string.IsNullOrWhiteSpace(executionId))
                executionId = "nt-" + execution.OrderId + "-" + execution.Time.ToUniversalTime().Ticks.ToString(CultureInfo.InvariantCulture);

            decimal commission = Convert.ToDecimal(execution.Commission, CultureInfo.InvariantCulture);
            double pointValue = 0;
            try
            {
                if (execution.Instrument != null && execution.Instrument.MasterInstrument != null)
                    pointValue = execution.Instrument.MasterInstrument.PointValue;
            }
            catch { }

            string json = "{" +
                JsonPair("external_execution_id", executionId) + "," +
                JsonPair("external_order_id", execution.OrderId) + "," +
                JsonPair("symbol", execution.Instrument != null ? execution.Instrument.FullName : "unknown") + "," +
                JsonPair("side", side) + "," +
                JsonNumber("quantity", Convert.ToDecimal(e.Quantity, CultureInfo.InvariantCulture)) + "," +
                JsonNumber("price", Convert.ToDecimal(e.Price, CultureInfo.InvariantCulture)) + "," +
                (commission > 0 ? JsonNumber("commission", commission) : "\"commission\":null") + "," +
                (pointValue > 0 ? JsonNumber("point_value", Convert.ToDecimal(pointValue, CultureInfo.InvariantCulture)) : "\"point_value\":null") + "," +
                JsonPair("currency", "USD") + "," +
                JsonPair("executed_at", execution.Time.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture)) + "," +
                "\"source_payload\":{" +
                    JsonPair("bridge_version", BridgeVersion) + "," +
                    JsonPair("ninjatrader_account", execution.Account.Name) + "," +
                    JsonPair("market_position", execution.MarketPosition.ToString()) +
                "}" +
            "}";

            Task.Run(() => SendExecution(json, executionId));
        }

        private void OnAccountItemUpdate(object sender, AccountItemEventArgs e)
        {
            if (e == null || e.Account == null)
                return;
            if (!string.Equals(e.Account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                return;
            if (e.AccountItem != AccountItem.CashValue
                && e.AccountItem != AccountItem.NetLiquidation
                && e.AccountItem != AccountItem.RealizedProfitLoss
                && e.AccountItem != AccountItem.UnrealizedProfitLoss)
                return;

            Account account = e.Account;
            Task.Run(() => SendAccountSnapshot(account, false));
        }

        private void SendExecution(string json, string executionId)
        {
            bool retryable;
            string error;
            if (PostJson("/broker-bridge/executions", json, out retryable, out error))
            {
                Write("SYNCED|execution=" + executionId);
                FlushQueue();
                return;
            }
            if (retryable)
            {
                QueueExecution(json);
                Write("QUEUED|execution=" + executionId + "|reason=" + error);
            }
            else
            {
                Write("REJECTED|execution=" + executionId + "|reason=" + error);
            }
        }

        private void Heartbeat()
        {
            bool retryable;
            string error;
            if (PostJson("/broker-bridge/heartbeat", "{}", out retryable, out error))
                FlushQueue();
            else if (!retryable)
                Write("HEARTBEAT_ERROR|" + error);
        }

        private void SendAccountSnapshot(Account account, bool force)
        {
            lock (snapshotLock)
            {
                if (!force && DateTime.UtcNow - lastSnapshotSentUtc < TimeSpan.FromSeconds(15))
                    return;

                string cash = SafeAccountValue(account, AccountItem.CashValue);
                string net = SafeAccountValue(account, AccountItem.NetLiquidation);
                string realized = SafeAccountValue(account, AccountItem.RealizedProfitLoss);
                string unrealized = SafeAccountValue(account, AccountItem.UnrealizedProfitLoss);
                string fingerprint = cash + "|" + net + "|" + realized + "|" + unrealized;
                if (!force && fingerprint == lastSnapshotFingerprint)
                    return;

                string json = "{" +
                    JsonPair("captured_at", DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture)) + "," +
                    JsonNullableNumber("cash_value", cash) + "," +
                    JsonNullableNumber("net_liquidation", net) + "," +
                    JsonNullableNumber("realized_pnl", realized) + "," +
                    JsonNullableNumber("unrealized_pnl", unrealized) +
                "}";
                bool retryable;
                string error;
                if (PostJson("/broker-bridge/account-snapshot", json, out retryable, out error))
                {
                    lastSnapshotSentUtc = DateTime.UtcNow;
                    lastSnapshotFingerprint = fingerprint;
                }
            }
        }

        private string SafeAccountValue(Account account, AccountItem item)
        {
            try
            {
                double value = account.Get(item, Currency.UsDollar);
                if (double.IsNaN(value) || double.IsInfinity(value))
                    return null;
                return value.ToString("0.########", CultureInfo.InvariantCulture);
            }
            catch
            {
                return null;
            }
        }

        private bool PostJson(string path, string json, out bool retryable, out string error)
        {
            retryable = true;
            error = "unknown";
            try
            {
                string url = config.ApiBase.TrimEnd('/') + path;
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "POST";
                request.ContentType = "application/json";
                request.Accept = "application/json";
                request.Timeout = 10000;
                request.ReadWriteTimeout = 10000;
                request.Headers[HttpRequestHeader.Authorization] = "Bearer " + config.BridgeToken;
                byte[] data = Encoding.UTF8.GetBytes(json);
                request.ContentLength = data.Length;
                using (Stream stream = request.GetRequestStream())
                    stream.Write(data, 0, data.Length);
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    int code = (int)response.StatusCode;
                    if (code >= 200 && code < 300)
                        return true;
                    retryable = code >= 500;
                    error = "HTTP " + code.ToString(CultureInfo.InvariantCulture);
                    return false;
                }
            }
            catch (WebException ex)
            {
                HttpWebResponse response = ex.Response as HttpWebResponse;
                if (response != null)
                {
                    int code = (int)response.StatusCode;
                    retryable = code >= 500 || code == 408 || code == 429;
                    error = "HTTP " + code.ToString(CultureInfo.InvariantCulture);
                }
                else
                {
                    retryable = true;
                    error = ex.Status.ToString();
                }
                return false;
            }
            catch (Exception ex)
            {
                retryable = true;
                error = ex.GetType().Name + ": " + ex.Message;
                return false;
            }
        }

        private void QueueExecution(string json)
        {
            lock (queueLock)
            {
                Directory.CreateDirectory(BridgeConfig.DataDirectory);
                File.AppendAllText(BridgeConfig.QueuePath, Convert.ToBase64String(Encoding.UTF8.GetBytes(json)) + Environment.NewLine);
            }
        }

        private void FlushQueue()
        {
            lock (queueLock)
            {
                if (!File.Exists(BridgeConfig.QueuePath))
                    return;
                string[] lines = File.ReadAllLines(BridgeConfig.QueuePath);
                if (lines.Length == 0)
                    return;
                List<string> remaining = new List<string>();
                int sent = 0;
                for (int index = 0; index < lines.Length; index++)
                {
                    string line = lines[index];
                    if (string.IsNullOrWhiteSpace(line))
                        continue;
                    string json;
                    try
                    {
                        json = Encoding.UTF8.GetString(Convert.FromBase64String(line.Trim()));
                    }
                    catch
                    {
                        continue;
                    }
                    bool retryable;
                    string error;
                    if (PostJson("/broker-bridge/executions", json, out retryable, out error))
                        sent++;
                    else
                    {
                        remaining.Add(line);
                        // Preserve ordering and stop hammering the endpoint after the first failure.
                        remaining.AddRange(lines.Skip(index + 1).Where(value => !string.IsNullOrWhiteSpace(value)));
                        break;
                    }
                }
                if (remaining.Count == 0)
                    File.Delete(BridgeConfig.QueuePath);
                else
                    File.WriteAllLines(BridgeConfig.QueuePath, remaining.ToArray());
                if (sent > 0)
                    Write("QUEUE_FLUSHED|count=" + sent.ToString(CultureInfo.InvariantCulture));
            }
        }

        private static string NormalizeSide(Execution execution)
        {
            string action = execution.Order != null ? execution.Order.OrderAction.ToString() : execution.MarketPosition.ToString();
            if (action.Equals("Buy", StringComparison.OrdinalIgnoreCase) || action.Equals("BuyToCover", StringComparison.OrdinalIgnoreCase) || action.Equals("Long", StringComparison.OrdinalIgnoreCase))
                return "buy";
            if (action.Equals("Sell", StringComparison.OrdinalIgnoreCase) || action.Equals("SellShort", StringComparison.OrdinalIgnoreCase) || action.Equals("Short", StringComparison.OrdinalIgnoreCase))
                return "sell";
            return null;
        }

        private static string JsonPair(string key, string value)
        {
            return "\"" + JsonEscape(key) + "\":\"" + JsonEscape(value ?? "") + "\"";
        }

        private static string JsonNumber(string key, decimal value)
        {
            return "\"" + JsonEscape(key) + "\":" + value.ToString(CultureInfo.InvariantCulture);
        }

        private static string JsonNullableNumber(string key, string value)
        {
            return "\"" + JsonEscape(key) + "\":" + (string.IsNullOrWhiteSpace(value) ? "null" : value);
        }

        private static string JsonEscape(string value)
        {
            if (value == null)
                return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
        }

        private void StopBridge()
        {
            if (heartbeatTimer != null)
            {
                heartbeatTimer.Dispose();
                heartbeatTimer = null;
            }
            Account.AccountStatusUpdate -= OnAccountStatusUpdate;
            foreach (Account account in subscribedAccounts.ToArray())
            {
                try
                {
                    account.ExecutionUpdate -= OnExecutionUpdate;
                    account.AccountItemUpdate -= OnAccountItemUpdate;
                }
                catch { }
            }
            subscribedAccounts.Clear();
            started = false;
            Write("STOPPED|subscriptions removed");
        }

        private static void Write(string message)
        {
            NinjaTrader.Code.Output.Process("JournalMeBridge|" + message, PrintTo.OutputTab1);
        }

        private sealed class BridgeConfig
        {
            public string ApiBase { get; private set; }
            public string BridgeToken { get; private set; }
            public string AccountName { get; private set; }
            public bool IsConfigured { get { return !string.IsNullOrWhiteSpace(ApiBase) && !string.IsNullOrWhiteSpace(BridgeToken) && !string.IsNullOrWhiteSpace(AccountName); } }

            public static string DataDirectory { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "JournalMe"); } }
            public static string ConfigPath { get { return Path.Combine(DataDirectory, "bridge.conf"); } }
            public static string QueuePath { get { return Path.Combine(DataDirectory, "bridge-queue.txt"); } }

            public static BridgeConfig Load()
            {
                BridgeConfig result = new BridgeConfig();
                if (!File.Exists(ConfigPath))
                    return result;
                foreach (string raw in File.ReadAllLines(ConfigPath))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line.StartsWith("#"))
                        continue;
                    int index = line.IndexOf('=');
                    if (index <= 0)
                        continue;
                    string key = line.Substring(0, index).Trim().ToLowerInvariant();
                    string value = line.Substring(index + 1).Trim();
                    if (key == "api_base") result.ApiBase = value.TrimEnd('/');
                    else if (key == "bridge_token") result.BridgeToken = value;
                    else if (key == "account_name") result.AccountName = value;
                }
                return result;
            }
        }
    }
}
