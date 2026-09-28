# JournalMe NinjaTrader Bridge v0.7.1

This bridge is read-only. It listens to NinjaTrader execution/account events and sends them to JournalMe. It contains no order submission, modification, cancellation, or flattening code.

## Setup

1. In JournalMe, open **Settings → Broker connections**.
2. Create/select the NinjaTrader connection for the JournalMe account.
3. Choose **Generate bridge key**. The key is shown only when generated/rotated.
4. On the PC running NinjaTrader, either paste the copied configuration into `%USERPROFILE%\Documents\JournalMe\bridge.conf`, or run:

```powershell
cd D:\PythonProjects\JournalMe
.\integrations\ninjatrader\configure_bridge.ps1 -AccountName LFE05085094850003
```

The helper prompts for the bridge key without echoing it. `bridge.conf` remains local to the PC. Do not commit or share it.

5. In NinjaTrader: **Control Center → New → NinjaScript Editor → AddOns → New AddOn**. Name it `JournalMeBridge`, replace the generated source with `JournalMeBridge.cs`, and press **F5** to compile.
6. Remove/disable the older `JournalMeProbe` after the bridge is working so the Output window is not noisy.
7. Open **Control Center → New → NinjaScript Output**. A configured bridge should show `JournalMeBridge|READY` and `JournalMeBridge|ACCOUNT`.

## Reliability

Execution uploads are idempotent by connection + NinjaTrader execution ID. If JournalMe cannot be reached, execution payloads are queued locally at `%USERPROFILE%\Documents\JournalMe\bridge-queue.txt` and retried later. Account snapshots are change-driven/throttled and are not queued.
