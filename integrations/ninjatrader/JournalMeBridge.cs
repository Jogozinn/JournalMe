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
        private const string BridgeVersion = "0.8.0";
        private readonly HashSet<Account> subscribedAccounts = new HashSet<Account>();
        private readonly object subscriptionsLock = new object();
        private readonly Dictionary<Account, string> sourceNamespaces = new Dictionary<Account, string>();
        private readonly object queueLock = new object();
        private readonly object snapshotLock = new object();
        private readonly Dictionary<string, DateTime> retryAfterUtc = new Dictionary<string, DateTime>();
        private string lastFailureCode;
        private DateTime lastFailureUtc = DateTime.MinValue;
        private readonly Dictionary<Account, DateTime> lastSnapshotSentUtc = new Dictionary<Account, DateTime>();
        private readonly Dictionary<Account, string> lastSnapshotFingerprint = new Dictionary<Account, string>();
        private Timer heartbeatTimer;
        private int heartbeatRunning;
        private bool started;
        private BridgeConfig config;

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
            Write("READY|version=" + BridgeVersion + "|readOnly=true");
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
            if (account == null)
                return;
            if (!string.IsNullOrWhiteSpace(config.AccountName) &&
                !string.Equals(account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                return;
            lock (subscriptionsLock)
            {
                if (subscribedAccounts.Contains(account))
                    return;
                account.ExecutionUpdate += OnExecutionUpdate;
                account.AccountItemUpdate += OnAccountItemUpdate;
                subscribedAccounts.Add(account);
            }
            Task.Run(() =>
            {
                DiscoverAccount(account);
                ReplayCurrentSession(account);
                SendAccountSnapshot(account, true);
            });
        }

        private void ReplayCurrentSession(Account account)
        {
            if (SourceNamespace(account) == null)
                return;
            // The documented collection contains only current-session executions.
            try
            {
                lock (account.Executions)
                {
                    foreach (Execution execution in account.Executions.ToArray())
                        ProcessExecution(execution, execution.Quantity, execution.Price);
                }
            }
            catch (Exception ex) { Write("SESSION_REPLAY_ERROR|" + ex.GetType().Name); }
        }

        private void OnAccountStatusUpdate(object sender, AccountStatusEventArgs e)
        {
            if (e == null || e.Account == null)
                return;
            SubscribeAccount(e.Account);
            Task.Run(() => { DiscoverAccount(e.Account); ReplayCurrentSession(e.Account); });
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            if (e == null || e.Execution == null || e.Execution.Account == null)
                return;
            ProcessExecution(e.Execution, e.Quantity, e.Price);
        }

        private void ProcessExecution(Execution execution, double quantity, double price)
        {
            if (execution == null || execution.Account == null ||
                (!string.IsNullOrWhiteSpace(config.AccountName) &&
                 !string.Equals(execution.Account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase)))
                return;
            string sourceNamespace = SourceNamespace(execution.Account);
            if (sourceNamespace == null)
                sourceNamespace = ""; // Retain an unresolved fill locally for review.
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
                JsonPair("source_namespace", sourceNamespace) + "," +
                JsonPair("source_account_name", execution.Account.Name) + "," +
                JsonPair("external_execution_id", executionId) + "," +
                JsonPair("external_order_id", execution.OrderId) + "," +
                JsonPair("symbol", execution.Instrument != null ? execution.Instrument.FullName : "unknown") + "," +
                JsonPair("side", side) + "," +
                JsonNumber("quantity", Convert.ToDecimal(quantity, CultureInfo.InvariantCulture)) + "," +
                JsonNumber("price", Convert.ToDecimal(price, CultureInfo.InvariantCulture)) + "," +
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

            // Persist before attempting delivery so a crash or network outage cannot lose a fill.
            QueueExecution(json, config.InstallationId + "|" + sourceNamespace + "|" + execution.Account.Name);
            Task.Run(() => FlushQueue());
        }

        private void OnAccountItemUpdate(object sender, AccountItemEventArgs e)
        {
            if (e == null || e.Account == null)
                return;
            if (!string.IsNullOrWhiteSpace(config.AccountName) &&
                !string.Equals(e.Account.Name, config.AccountName, StringComparison.OrdinalIgnoreCase))
                return;
            if (e.AccountItem != AccountItem.CashValue
                && e.AccountItem != AccountItem.NetLiquidation
                && e.AccountItem != AccountItem.RealizedProfitLoss
                && e.AccountItem != AccountItem.UnrealizedProfitLoss)
                return;

            Account account = e.Account;
            Task.Run(() => SendAccountSnapshot(account, false));
        }

        private string SourceNamespace(Account account)
        {
            string current = account.Connection != null && account.Connection.Options != null
                ? account.Connection.Options.Name : null;
            lock (subscriptionsLock)
            {
                if (!string.IsNullOrWhiteSpace(current))
                    sourceNamespaces[account] = current;
                string known;
                return sourceNamespaces.TryGetValue(account, out known) ? known : null;
            }
        }

        private void DiscoverAccount(Account account)
        {
            string sourceNamespace = SourceNamespace(account);
            if (sourceNamespace == null)
                return;
            bool retryable;
            string error;
            string json = "{" + JsonPair("source_namespace", sourceNamespace) + "," +
                JsonPair("source_account_name", account.Name) + "}";
            PostJson("/broker-bridge/discovered-accounts", json, out retryable, out error);
        }

        private void Heartbeat()
        {
            if (Interlocked.Exchange(ref heartbeatRunning, 1) != 0)
                return;
            try
            {
                SubscribeExistingAccounts();
                int pending;
                int legacyPending;
                string failure;
                DateTime failureAt;
                lock (queueLock)
                {
                    pending = File.Exists(BridgeConfig.QueuePath) ? File.ReadAllLines(BridgeConfig.QueuePath).Length : 0;
                    legacyPending = File.Exists(BridgeConfig.LegacyQueuePath) ? File.ReadAllLines(BridgeConfig.LegacyQueuePath).Length : 0;
                    failure = lastFailureCode;
                    failureAt = lastFailureUtc;
                }
                string payload = "{" + JsonNumber("pending_uploads", pending) + "," +
                    JsonNumber("legacy_pending_uploads", legacyPending) + "," +
                    (failure == null ? "\"last_failure_code\":null" : JsonPair("last_failure_code", failure)) + "," +
                    (failureAt == DateTime.MinValue ? "\"last_failure_at\":null" : JsonPair("last_failure_at", failureAt.ToString("O", CultureInfo.InvariantCulture))) + "}";
                bool retryable;
                string error;
                if (PostJson("/broker-bridge/heartbeat", payload, out retryable, out error))
                {
                    Account[] accounts;
                    lock (subscriptionsLock)
                        accounts = subscribedAccounts.ToArray();
                    foreach (Account account in accounts)
                        DiscoverAccount(account);
                    FlushQueue();
                    FlushLegacyQueue();
                }
                else if (!retryable)
                    Write("HEARTBEAT_ERROR|" + error);
            }
            finally { Interlocked.Exchange(ref heartbeatRunning, 0); }
        }

        private void SendAccountSnapshot(Account account, bool force)
        {
            string sourceNamespace = SourceNamespace(account);
            if (sourceNamespace == null)
                return;
            lock (snapshotLock)
            {
                DateTime lastSent;
                if (!force && lastSnapshotSentUtc.TryGetValue(account, out lastSent) &&
                    DateTime.UtcNow - lastSent < TimeSpan.FromSeconds(15))
                    return;

                string cash = SafeAccountValue(account, AccountItem.CashValue);
                string net = SafeAccountValue(account, AccountItem.NetLiquidation);
                string realized = SafeAccountValue(account, AccountItem.RealizedProfitLoss);
                string unrealized = SafeAccountValue(account, AccountItem.UnrealizedProfitLoss);
                string fingerprint = cash + "|" + net + "|" + realized + "|" + unrealized;
                string previous;
                if (!force && lastSnapshotFingerprint.TryGetValue(account, out previous) && fingerprint == previous)
                    return;

                string json = "{" +
                    JsonPair("source_namespace", sourceNamespace) + "," +
                    JsonPair("source_account_name", account.Name) + "," +
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
                    lastSnapshotSentUtc[account] = DateTime.UtcNow;
                    lastSnapshotFingerprint[account] = fingerprint;
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
                error = ex.GetType().Name;
                return false;
            }
        }

        private void QueueExecution(string json, string sourceKey)
        {
            lock (queueLock)
            {
                Directory.CreateDirectory(BridgeConfig.DataDirectory);
                string line = Convert.ToBase64String(Encoding.UTF8.GetBytes(sourceKey)) + "." +
                    Convert.ToBase64String(Encoding.UTF8.GetBytes(json));
                if (File.Exists(BridgeConfig.QueuePath) && File.ReadAllLines(BridgeConfig.QueuePath).Contains(line))
                    return;
                File.AppendAllText(BridgeConfig.QueuePath, line + Environment.NewLine);
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
                    string sourceKey;
                    try
                    {
                        string[] parts = line.Trim().Split(new char[] { '.' }, 2);
                        sourceKey = Encoding.UTF8.GetString(Convert.FromBase64String(parts[0]));
                        json = Encoding.UTF8.GetString(Convert.FromBase64String(parts[1]));
                    }
                    catch
                    {
                        remaining.Add(line);
                        continue;
                    }
                    if (!sourceKey.StartsWith(config.InstallationId + "|", StringComparison.Ordinal))
                    {
                        // A queue from another installation must not be reattributed.
                        remaining.Add(line);
                        continue;
                    }
                    DateTime retryAfter;
                    if (retryAfterUtc.TryGetValue(sourceKey, out retryAfter) && DateTime.UtcNow < retryAfter)
                    {
                        remaining.Add(line);
                        continue;
                    }
                    bool retryable;
                    string error;
                    if (PostJson("/broker-bridge/executions", json, out retryable, out error))
                    {
                        sent++;
                        retryAfterUtc.Remove(sourceKey);
                    }
                    else
                    {
                        remaining.Add(line);
                        lastFailureCode = error;
                        lastFailureUtc = DateTime.UtcNow;
                        retryAfterUtc[sourceKey] = DateTime.UtcNow.AddSeconds(retryable ? 30 : 60);
                        // A rejected account does not block other authorized accounts.
                    }
                    if (index >= 24)
                    {
                        remaining.AddRange(lines.Skip(index + 1).Where(value => !string.IsNullOrWhiteSpace(value)));
                        break;
                    }
                }
                if (remaining.Count == 0)
                    File.Delete(BridgeConfig.QueuePath);
                else
                {
                    string temporary = BridgeConfig.QueuePath + ".tmp";
                    File.WriteAllLines(temporary, remaining.ToArray());
                    File.Replace(temporary, BridgeConfig.QueuePath, null);
                }
                if (sent > 0)
                    Write("QUEUE_FLUSHED|count=" + sent.ToString(CultureInfo.InvariantCulture));
            }
        }

        private void FlushLegacyQueue()
        {
            // Old files have no connection namespace. Only the original single-account
            // token can submit them. Leave the file intact if a new installation key is used.
            if (string.IsNullOrWhiteSpace(config.AccountName))
                return;
            lock (queueLock)
            {
                if (!File.Exists(BridgeConfig.LegacyQueuePath))
                    return;
                string[] lines = File.ReadAllLines(BridgeConfig.LegacyQueuePath);
                List<string> remaining = new List<string>();
                for (int index = 0; index < lines.Length; index++)
                {
                    string line = lines[index];
                    if (string.IsNullOrWhiteSpace(line))
                        continue;
                    string json;
                    try { json = Encoding.UTF8.GetString(Convert.FromBase64String(line.Trim())); }
                    catch { remaining.Add(line); continue; }
                    if (!json.Contains(JsonPair("ninjatrader_account", config.AccountName)))
                    {
                        remaining.Add(line);
                        continue;
                    }
                    bool retryable;
                    string error;
                    if (!PostJson("/broker-bridge/executions", json, out retryable, out error))
                    {
                        remaining.Add(line);
                        lastFailureCode = error;
                        lastFailureUtc = DateTime.UtcNow;
                    }
                    if (index >= 24)
                    {
                        remaining.AddRange(lines.Skip(index + 1).Where(value => !string.IsNullOrWhiteSpace(value)));
                        break;
                    }
                }
                if (remaining.Count == 0)
                    File.Delete(BridgeConfig.LegacyQueuePath);
                else
                {
                    string temporary = BridgeConfig.LegacyQueuePath + ".tmp";
                    File.WriteAllLines(temporary, remaining.ToArray());
                    File.Replace(temporary, BridgeConfig.LegacyQueuePath, null);
                }
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
            lock (subscriptionsLock)
            {
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
                sourceNamespaces.Clear();
            }
            lock (snapshotLock) { lastSnapshotSentUtc.Clear(); lastSnapshotFingerprint.Clear(); }
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
            public string InstallationId
            {
                get
                {
                    string[] parts = (BridgeToken ?? "").Split('.');
                    return parts.Length == 3 && parts[0] == "jmbrg" ? parts[1] : "";
                }
            }
            public bool IsConfigured { get { return !string.IsNullOrWhiteSpace(ApiBase) && !string.IsNullOrWhiteSpace(InstallationId); } }

            public static string DataDirectory { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "JournalMe"); } }
            public static string ConfigPath { get { return Path.Combine(DataDirectory, "bridge.conf"); } }
            public static string QueuePath { get { return Path.Combine(DataDirectory, "bridge-queue-v2.txt"); } }
            public static string LegacyQueuePath { get { return Path.Combine(DataDirectory, "bridge-queue.txt"); } }

            public static BridgeConfig Load()
            {
                BridgeConfig result = new BridgeConfig();
                if (!File.Exists(ConfigPath))
                    return result;
                foreach (string raw in File.ReadAllLines(ConfigPath))
                {
                    string line = raw.Trim().TrimStart('\uFEFF');
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
