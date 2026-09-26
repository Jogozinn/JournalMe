"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { PresetWizard } from "@/components/preset-wizard";
import { ErrorState, PageHeader, Pnl } from "@/components/ui";
import { api, money } from "@/lib/api";
import type { Account } from "@/lib/types";

type AccountGroup = {
  id: string;
  name: string;
  description: string | null;
  account_ids: string[];
};

function lifecycleLabel(account: Account): string {
  return account.lifecycle_status.replaceAll("_", " ");
}

function planLabel(account: Account): string {
  if (!account.active_plan) return account.account_type;
  return `${account.active_plan.plan_family} · ${account.active_plan.phase}`;
}

function AccountCard({
  account,
  current,
  onMakeCurrent,
  onArchive,
  busy,
}: {
  account: Account;
  current: boolean;
  onMakeCurrent: () => void;
  onArchive: () => void;
  busy: boolean;
}) {
  return (
    <article className={`card account-card ${current ? "selected-card" : ""}`}>
      <header className="account-card-heading">
        <div className="account-card-title">
          <div className="account-card-meta">
            <span>{account.provider}</span>
            <span aria-hidden="true">•</span>
            <span>{planLabel(account)}</span>
          </div>
          <h2>{account.name}</h2>
        </div>
        <div className="account-state-badges">
          {current && <span className="current-label">Current</span>}
          <span className={`account-state ${account.lifecycle_status}`}>
            {lifecycleLabel(account)}
          </span>
        </div>
      </header>

      <div className="account-kpi-row">
        <div>
          <span>Balance</span>
          <strong>{money(account.current_balance, account.currency)}</strong>
        </div>
        <div>
          <span>Net P&amp;L</span>
          <Pnl value={account.net_pnl}>
            <strong>{money(account.net_pnl, account.currency)}</strong>
          </Pnl>
        </div>
        <div>
          <span>Starting</span>
          <strong>{money(account.starting_balance, account.currency)}</strong>
        </div>
      </div>

      <div className="account-card-details">
        {account.active_plan?.account_size && (
          <span>{money(account.active_plan.account_size, account.currency)} plan</span>
        )}
        <span>{account.timezone.replace("America/", "")}</span>
        <span className="capitalize">{account.account_type}</span>
        {account.configuration_required && (
          <span className="warning-text">Needs configuration</span>
        )}
      </div>

      <footer className="account-card-actions">
        <div>
          {!current && (
            <button className="button quiet compact" type="button" onClick={onMakeCurrent} disabled={busy}>
              Make current
            </button>
          )}
        </div>
        <div>
          <Link className={`button compact ${busy ? "disabled" : ""}`} aria-disabled={busy} href={busy ? "#" : `/accounts/${account.id}`}>
            Manage
          </Link>
          <button className="button quiet compact" type="button" onClick={onArchive} disabled={busy} aria-busy={busy}>
            {busy ? <><span className="button-spinner" /> Archiving…</> : "Archive"}
          </button>
        </div>
      </footer>
    </article>
  );
}

export default function AccountsPage() {
  const { accounts, account, setAccountId, refresh } = useAccount();
  const [creating, setCreating] = useState(false);
  const [groupOpen, setGroupOpen] = useState(false);
  const [groups, setGroups] = useState<AccountGroup[]>([]);
  const [allAccounts, setAllAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const loadManagementData = useCallback(async () => {
    try {
      const [nextAccounts, nextGroups] = await Promise.all([
        api<Account[]>("/accounts?include_archived=true"),
        api<AccountGroup[]>("/account-groups"),
      ]);
      setAllAccounts(nextAccounts);
      setGroups(nextGroups);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Account management data could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    void loadManagementData();
  }, [loadManagementData]);

  const archivedAccounts = useMemo(
    () => allAccounts.filter((item) => !item.active),
    [allAccounts],
  );

  async function createGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/account-groups", {
        method: "POST",
        body: JSON.stringify({
          name: form.get("group_name"),
          description: form.get("group_description") || null,
          account_ids: form.getAll("group_account_ids"),
        }),
      });
      event.currentTarget.reset();
      setGroupOpen(false);
      await loadManagementData();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account group could not be created.");
    }
  }

  async function archiveAccount(id: string) {
    setPendingAction(`archive:${id}`);
    setError("");
    try {
      await api(`/accounts/${id}/archive`, { method: "POST" });
      await Promise.all([refresh(), loadManagementData()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account could not be archived.");
    } finally {
      setPendingAction(null);
    }
  }

  async function restoreAccount(id: string) {
    setPendingAction(`restore:${id}`);
    setError("");
    try {
      await api(`/accounts/${id}/restore`, { method: "POST" });
      await Promise.all([refresh(), loadManagementData()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account could not be restored.");
    } finally {
      setPendingAction(null);
    }
  }

  async function createdAccount() {
    await Promise.all([refresh(), loadManagementData()]);
  }

  return (
    <div className="accounts-page">
      <PageHeader
        eyebrow="Workspace"
        title="Accounts"
        description="Keep live accounts in front of you and move finished accounts into history without losing their journal."
        action={(
          <button className="button primary" type="button" onClick={() => setCreating(true)}>
            + Add account
          </button>
        )}
      />

      {error && <ErrorState message={error} />}

      <section className="account-overview-strip" aria-label="Account overview">
        <div>
          <span>Active</span>
          <strong>{accounts.length}</strong>
        </div>
        <div>
          <span>Archived</span>
          <strong>{archivedAccounts.length}</strong>
        </div>
        <div>
          <span>Current</span>
          <strong>{account?.name ?? "None selected"}</strong>
        </div>
      </section>

      <section className="account-section">
        <div className="section-title account-section-title">
          <div>
            <p className="eyebrow">Current workspace</p>
            <h2>Active accounts</h2>
          </div>
          <span>{accounts.length} active</span>
        </div>

        {!accounts.length ? (
          <div className="card compact-empty account-empty-state">
            <div>
              <h3>No active accounts</h3>
              <p className="muted">
                Restore an archived account or add a new one when you are ready to trade again.
              </p>
            </div>
            <button className="button primary compact" type="button" onClick={() => setCreating(true)}>
              Add account
            </button>
          </div>
        ) : (
          <div className="account-grid">
            {accounts.map((item) => (
              <AccountCard
                key={item.id}
                account={item}
                current={item.id === account?.id}
                onMakeCurrent={() => setAccountId(item.id)}
                onArchive={() => void archiveAccount(item.id)}
                busy={pendingAction === `archive:${item.id}`}
              />
            ))}
          </div>
        )}
      </section>

      {archivedAccounts.length > 0 && (
        <details className="card archived-accounts">
          <summary>
            <span>
              <p className="eyebrow">History</p>
              <strong>Archived accounts</strong>
            </span>
            <span className="archived-summary-meta">{archivedAccounts.length} retained</span>
          </summary>
          <p className="muted archived-copy">
            Archived accounts keep every trade, journal, balance, review, capture, and analytic record.
          </p>
          <div className="archived-account-list">
            {archivedAccounts.map((item) => (
              <article key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <span>
                    {item.provider} · {lifecycleLabel(item)} · {money(item.current_balance, item.currency)}
                  </span>
                </div>
                <div>
                  <Link className="button quiet compact" href={`/accounts/${item.id}`}>
                    Manage
                  </Link>
                  <button className="button compact" type="button" disabled={pendingAction === `restore:${item.id}`} aria-busy={pendingAction === `restore:${item.id}`} onClick={() => void restoreAccount(item.id)}>
                    {pendingAction === `restore:${item.id}` ? <><span className="button-spinner" /> Restoring…</> : "Restore"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </details>
      )}

      <details className="card account-groups-panel" open={groupOpen || groups.length > 0}>
        <summary className="account-groups-summary" onClick={(event) => {
          if (groups.length > 0) return;
          event.preventDefault();
          setGroupOpen((value) => !value);
        }}>
          <div>
            <p className="eyebrow">Optional organization</p>
            <strong>Account groups</strong>
            <span>Group related accounts without merging their histories.</span>
          </div>
          <span>{groups.length ? `${groups.length} group${groups.length === 1 ? "" : "s"}` : "Set up"}</span>
        </summary>

        <div className="account-groups-body">
          {!!groups.length && (
            <div className="group-list">
              {groups.map((group) => (
                <div key={group.id}>
                  <strong>{group.name}</strong>
                  <span>
                    {group.account_ids
                      .map((accountId) => allAccounts.find((item) => item.id === accountId)?.name ?? "Unavailable account")
                      .join(" · ")}
                  </span>
                  {group.description && <small>{group.description}</small>}
                </div>
              ))}
            </div>
          )}

          {!groups.length && !groupOpen && (
            <div className="compact-empty">
              <p className="muted">No groups yet.</p>
              <button className="button compact" type="button" onClick={() => setGroupOpen(true)}>
                Create group
              </button>
            </div>
          )}

          {!!groups.length && (
            <button className="button quiet compact" type="button" onClick={() => setGroupOpen((value) => !value)}>
              {groupOpen ? "Close form" : "+ Create group"}
            </button>
          )}

          {groupOpen && (
            <form className="form-grid compact-group-form" onSubmit={createGroup}>
              <div className="field">
                <label htmlFor="group_name">Group name</label>
                <input id="group_name" name="group_name" placeholder="e.g. September Lucid evaluations" required maxLength={120} />
              </div>
              <div className="field">
                <label htmlFor="group_description">Description</label>
                <input id="group_description" name="group_description" placeholder="Optional note" maxLength={500} />
              </div>
              <fieldset className="span-2 day-playbooks group-account-picker">
                <legend>Accounts</legend>
                {allAccounts.map((item) => (
                  <label key={item.id}>
                    <input type="checkbox" name="group_account_ids" value={item.id} /> {item.name}
                  </label>
                ))}
              </fieldset>
              <div className="form-actions span-2">
                <button className="button quiet" type="button" onClick={() => setGroupOpen(false)}>
                  Cancel
                </button>
                <button className="button primary">Save group</button>
              </div>
            </form>
          )}
        </div>
      </details>

      {creating && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.currentTarget === event.target) setCreating(false);
        }}>
          <section className="modal-card account-create-modal" role="dialog" aria-modal="true" aria-label="Add JournalMe account" id="add-account">
            <PresetWizard
              onSaved={createdAccount}
              onCancel={() => {
                setCreating(false);
                void loadManagementData();
              }}
            />
          </section>
        </div>
      )}
    </div>
  );
}
