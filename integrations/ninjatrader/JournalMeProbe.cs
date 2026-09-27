#region Using declarations
using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.NinjaScript;
#endregion

// Read-only discovery probe for JournalMe.
// It subscribes to NinjaTrader account events and writes observations to the
// NinjaScript Output window. It contains no order submission, modification,
// cancellation, or flattening code and sends no data over the network.
namespace NinjaTrader.NinjaScript.AddOns
{
    public class JournalMeProbe : AddOnBase
    {
        private readonly HashSet<Account> subscribedAccounts = new HashSet<Account>();
        private bool started;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "JournalMeProbe";
                Description = "Read-only JournalMe account and execution discovery probe";
            }
            else if (State == State.Terminated)
            {
                StopProbe();
            }
        }

        protected override void OnWindowCreated(Window window)
        {
            if (!(window is ControlCenter) || started)
                return;

            started = true;
            Account.AccountStatusUpdate += OnAccountStatusUpdate;
            SubscribeExistingAccounts();
            Write("READY|JournalMeProbe is listening for read-only account events");
        }

        protected override void OnWindowDestroyed(Window window)
        {
            if (window is ControlCenter)
                StopProbe();
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

            account.ExecutionUpdate += OnExecutionUpdate;
            account.AccountItemUpdate += OnAccountItemUpdate;
            account.PositionUpdate += OnPositionUpdate;
            subscribedAccounts.Add(account);

            string connection = account.Connection != null && account.Connection.Options != null
                ? account.Connection.Options.Name
                : "none";
            string status = account.Connection != null ? account.Connection.Status.ToString() : "unknown";
            string cash = SafeAccountValue(account, AccountItem.CashValue);
            string netLiquidation = SafeAccountValue(account, AccountItem.NetLiquidation);

            Write(string.Format(
                "ACCOUNT|name={0}|connection={1}|status={2}|cash={3}|netLiquidation={4}",
                account.Name,
                connection,
                status,
                cash,
                netLiquidation));
        }

        private string SafeAccountValue(Account account, AccountItem item)
        {
            try
            {
                return account.Get(item, Currency.UsDollar).ToString("0.00");
            }
            catch
            {
                return "unavailable";
            }
        }

        private void OnAccountStatusUpdate(object sender, AccountStatusEventArgs e)
        {
            SubscribeAccount(e.Account);
            Write(string.Format("ACCOUNT_STATUS|name={0}|status={1}", e.Account.Name, e.Status));
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            if (e == null || e.Execution == null)
                return;

            Execution execution = e.Execution;
            string account = execution.Account != null ? execution.Account.Name : "unknown";
            string instrument = execution.Instrument != null ? execution.Instrument.FullName : "unknown";
            string action = execution.Order != null ? execution.Order.OrderAction.ToString() : execution.MarketPosition.ToString();

            Write(string.Format(
                "EXECUTION|account={0}|instrument={1}|action={2}|quantity={3}|price={4}|executionId={5}|orderId={6}|commission={7}|time={8:O}",
                account,
                instrument,
                action,
                e.Quantity,
                e.Price,
                execution.ExecutionId,
                execution.OrderId,
                execution.Commission,
                execution.Time));
        }

        private void OnAccountItemUpdate(object sender, AccountItemEventArgs e)
        {
            if (e == null || e.Account == null)
                return;

            if (e.AccountItem != AccountItem.CashValue
                && e.AccountItem != AccountItem.NetLiquidation
                && e.AccountItem != AccountItem.RealizedProfitLoss
                && e.AccountItem != AccountItem.UnrealizedProfitLoss)
                return;

            Write(string.Format(
                "ACCOUNT_ITEM|account={0}|item={1}|value={2}|currency={3}|time={4:O}",
                e.Account.Name,
                e.AccountItem,
                e.Value,
                e.Currency,
                e.Time));
        }

        private void OnPositionUpdate(object sender, PositionEventArgs e)
        {
            if (e == null || e.Position == null)
                return;

            string account = e.Position.Account != null ? e.Position.Account.Name : "unknown";
            string instrument = e.Position.Instrument != null ? e.Position.Instrument.FullName : "unknown";
            Write(string.Format(
                "POSITION|account={0}|instrument={1}|marketPosition={2}|quantity={3}|averagePrice={4}",
                account,
                instrument,
                e.MarketPosition,
                e.Quantity,
                e.AveragePrice));
        }

        private void StopProbe()
        {
            if (!started && subscribedAccounts.Count == 0)
                return;

            Account.AccountStatusUpdate -= OnAccountStatusUpdate;
            foreach (Account account in subscribedAccounts.ToArray())
            {
                try
                {
                    account.ExecutionUpdate -= OnExecutionUpdate;
                    account.AccountItemUpdate -= OnAccountItemUpdate;
                    account.PositionUpdate -= OnPositionUpdate;
                }
                catch
                {
                    // Shutdown should continue even if an account disappears first.
                }
            }
            subscribedAccounts.Clear();
            started = false;
            Write("STOPPED|JournalMeProbe subscriptions removed");
        }

        private static void Write(string message)
        {
            NinjaTrader.Code.Output.Process("JournalMe|" + message, PrintTo.OutputTab1);
        }
    }
}
