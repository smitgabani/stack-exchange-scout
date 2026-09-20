"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ConfirmDialog } from "../../confirm-dialog";
import { type Account, money, scoutApi, when } from "@/lib/scout-api";
import styles from "../../workspace.module.css";

export default function AccountsPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [removing, setRemoving] = useState<Account | null>(null);
  const [renaming, setRenaming] = useState<Account | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  // Which account's spend is being edited, and the raw text while typing —
  // kept as a string so a half-typed "0." is not coerced to a number mid-edit.
  const [editingSpend, setEditingSpend] = useState<number | null>(null);
  const [spendValue, setSpendValue] = useState("");

  const { data, isLoading } = useQuery({ queryKey: ["accounts"], queryFn: scoutApi.listAccounts });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["accounts"] });

  const add = useMutation({
    mutationFn: () => scoutApi.addAccount({ api_key: apiKey, label, make_active: true }),
    onSuccess: async (account) => {
      setMessage(
        account.reachable === false
          ? `Saved “${account.label}”, but Yutori rejected it: ${account.error}. Fix the key before running anything.`
          : `Added “${account.label}” and made it active.`,
      );
      setAdding(false);
      setAddError(null);
      setLabel("");
      setApiKey("");
      await refresh();
    },
    // Shown inside the dialog rather than behind it: a rejected key means the
    // form still has work to do, and closing it would throw away what was typed.
    onError: (e: Error) => setAddError(e.message),
  });

  const rename = useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      scoutApi.renameAccount(id, label),
    onSuccess: async (a) => {
      setMessage(`Renamed to “${a.label}”.`);
      setRenaming(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const setSpend = useMutation({
    mutationFn: ({ id, amount }: { id: number; amount: number | null }) =>
      scoutApi.setAccountSpend(id, amount),
    onSuccess: async (a) => {
      setMessage(
        a.spend_override_usd === null
          ? `“${a.label}” is back to the calculated total.`
          : `“${a.label}” spend set to ${money(a.spend_override_usd)}.`,
      );
      setEditingSpend(null);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  function saveSpend(account: Account) {
    const trimmed = spendValue.trim();
    // Empty means "stop correcting", which is different from zero — an
    // account really can have cost nothing.
    if (trimmed === "") {
      setSpend.mutate({ id: account.id, amount: null });
      return;
    }
    const amount = Number(trimmed.replace(/^\$/, ""));
    if (!Number.isFinite(amount) || amount < 0) {
      setMessage("Enter a dollar amount like 0.70, or leave it empty to use the calculated total.");
      return;
    }
    setSpend.mutate({ id: account.id, amount });
  }

  const activate = useMutation({
    mutationFn: (id: number) => scoutApi.activateAccount(id),
    onSuccess: async (a) => {
      setMessage(`“${a.label}” is now the active key. Runs will be charged to it.`);
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => scoutApi.removeAccount(id),
    onSuccess: async (r) => {
      setMessage(
        `Removed “${r.label}”. ${r.kept.questions} questions and ${r.kept.runs} runs were kept.`,
      );
      await refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  if (isLoading || !data) return <main className={styles.page}>Loading…</main>;

  const accounts = data.accounts.filter((a) => a.key_name === "yutori_api_key");

  return (
    <main className={styles.page}>
      <div className={styles.head}>
        <div>
          <div className={styles.title}>Yutori accounts</div>
          <div className={styles.sub}>
            Keys can belong to different accounts. A run is charged to whichever one is active
            when you press Run.
          </div>
        </div>
        <div className={styles.actions}>
          <button className={styles.primary} onClick={() => setAdding(true)}>Add a key</button>
        </div>
      </div>

      {message && <div className={styles.notice}>{message}</div>}

      {accounts.length === 0 ? (
        <div className={styles.empty}>No Yutori keys stored. Add one to run anything.</div>
      ) : (
        <div className={styles.list}>
          {accounts.map((account) => (
            <div key={account.id} className={styles.item}>
              <div>
                <div className={styles.itemName}>
                  <Link href={`/yutori/accounts/${account.id}`}>{account.label}</Link>
                  {account.is_active ? (
                    <span className={`${styles.pill} ${styles.pillOn}`}>Active</span>
                  ) : (
                    <span className={styles.pill}>Stored</span>
                  )}
                  {account.account_fingerprint === null && (
                    <span className={`${styles.pill} ${styles.pillDraft}`}>Owner unknown</span>
                  )}
                </div>
                <div className={styles.itemMeta}>
                  Added {when(account.created_at)} · {money(account.spend_usd)} spent
                  {/* "$0.70 spent over 1 run" reads as a contradiction when the
                      figure was corrected precisely because runs are missing
                      from the history. Only tie the two together when the
                      number actually came from those runs. */}
                  {account.spend_override_usd === null ? (
                    <>
                      {" "}
                      over {account.run_count} run{account.run_count === 1 ? "" : "s"}
                    </>
                  ) : (
                    <>
                      {" "}
                      ({account.run_count} run{account.run_count === 1 ? "" : "s"} recorded)
                    </>
                  )}{" "}
                  · {account.instance_count} object
                  {account.instance_count === 1 ? "" : "s"} at Yutori
                </div>
                <div className={`${styles.itemQuery} ${styles.mono}`}>
                  fingerprint {account.account_fingerprint ?? "not recorded — set on first use"}
                </div>
              </div>
              <div className={styles.itemSide}>
                {editingSpend === account.id ? (
                  <div className={styles.yield}>
                    <input
                      className={styles.input}
                      style={{ width: "96px", textAlign: "right" }}
                      value={spendValue}
                      onChange={(e) => setSpendValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveSpend(account);
                        if (e.key === "Escape") setEditingSpend(null);
                      }}
                      placeholder={account.computed_spend_usd.toFixed(2)}
                      inputMode="decimal"
                      autoFocus
                      aria-label={`Amount charged to ${account.label}`}
                    />
                    <div className={styles.actions} style={{ marginTop: "6px" }}>
                      <button
                        className={`${styles.primary} ${styles.tiny}`}
                        onClick={() => saveSpend(account)}
                        disabled={setSpend.isPending}
                      >
                        Save
                      </button>
                      <button
                        className={`${styles.secondary} ${styles.tiny}`}
                        onClick={() => setEditingSpend(null)}
                        disabled={setSpend.isPending}
                      >
                        Cancel
                      </button>
                    </div>
                    <span className={styles.hint}>
                      Empty = use the calculated {money(account.computed_spend_usd)}
                    </span>
                  </div>
                ) : (
                  <div className={styles.yield}>
                    <b>{money(account.spend_usd)}</b>
                    <br />
                    <span className={styles.hint}>
                      charged here
                      {/* When the two disagree, say so. The gap is unrecorded
                          run history, and hiding it would make the corrected
                          figure look like something the app worked out. */}
                      {account.spend_override_usd !== null && (
                        <>
                          {" "}
                          · you set this
                          <br />
                          calculated {money(account.computed_spend_usd)}
                        </>
                      )}
                    </span>
                    <br />
                    <button
                      className={`${styles.textButton} ${styles.tiny}`}
                      onClick={() => {
                        setSpendValue(
                          account.spend_override_usd !== null
                            ? String(account.spend_override_usd)
                            : "",
                        );
                        setEditingSpend(account.id);
                      }}
                    >
                      Edit amount
                    </button>
                  </div>
                )}
                <div className={styles.actions}>
                  {!account.is_active && (
                    <button
                      className={`${styles.secondary} ${styles.tiny}`}
                      onClick={() => activate.mutate(account.id)}
                      disabled={activate.isPending}
                    >
                      Make active
                    </button>
                  )}
                  <button
                    className={`${styles.secondary} ${styles.tiny}`}
                    onClick={() => { setRenameValue(account.label); setRenaming(account); }}
                  >
                    Rename
                  </button>
                  <Link className={`${styles.secondary} ${styles.tiny}`} href={`/yutori/accounts/${account.id}`}>
                    Inspect
                  </Link>
                  <button
                    className={`${styles.danger} ${styles.tiny}`}
                    onClick={() => setRemoving(account)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={styles.grid2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>Removed when you delete a key</div>
          <ul className={styles.hint} style={{ paddingLeft: "18px", lineHeight: 1.8 }}>
            <li>The stored key itself</li>
            <li>This app&apos;s ability to reach that account</li>
            <li>The account from the active-key picker</li>
          </ul>
        </div>
        <div className={styles.card}>
          <div className={styles.cardTitle}>Kept</div>
          <ul className={styles.hint} style={{ paddingLeft: "18px", lineHeight: 1.8 }}>
            <li>Every question, digest and challenge it found</li>
            <li>Run history, still showing what it cost</li>
            <li>Your saved scouts — they were never remote</li>
          </ul>
          <p className={styles.hint}>
            Discovered questions are what stop the app rediscovering — and re-paying for — what
            you have already seen.
          </p>
        </div>
      </div>

      <ConfirmDialog
        open={renaming !== null}
        title="Rename account"
        body={
          <>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="acct-rename">Name</label>
              <input
                id="acct-rename"
                className={styles.input}
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
              />
            </div>
            <p className={styles.hint} style={{ marginTop: "10px" }}>
              This is how Scouts from different accounts are labelled on the Monitors page.
            </p>
          </>
        }
        confirmLabel="Rename"
        busy={rename.isPending}
        onCancel={() => setRenaming(null)}
        onConfirm={() => {
          if (renaming && renameValue.trim()) rename.mutate({ id: renaming.id, label: renameValue.trim() });
        }}
      />

      <ConfirmDialog
        open={adding}
        title="Add a Yutori key"
        body={
          <>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="acct-label">Name it something you&apos;ll recognise</label>
              <input
                id="acct-label"
                className={styles.input}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Friend's key"
              />
            </div>
            <div className={styles.field} style={{ marginTop: "12px" }}>
              <label className={styles.label} htmlFor="acct-key">API key</label>
              <input
                id="acct-key"
                className={styles.input}
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="yut_…"
              />
            </div>
            {addError && (
              <div className={styles.alert} style={{ marginTop: "14px" }}>
                <strong>Not added.</strong> {addError}
              </div>
            )}
            <p className={styles.hint} style={{ marginTop: "12px" }}>
              The key is checked against Yutori before it is trusted — a broken key otherwise
              looks fine until the moment it costs you a run. A key from an account you have
              already added is refused, so one account&apos;s spend is never split in two.
            </p>
          </>
        }
        confirmLabel="Add key"
        busy={add.isPending}
        onCancel={() => { setAdding(false); setAddError(null); }}
        onConfirm={() => { setAddError(null); add.mutate(); }}
      />

      <ConfirmDialog
        open={removing !== null}
        title={`Remove “${removing?.label ?? ""}”?`}
        body={
          <p>
            The key goes and this app can no longer reach that account. Every question it found
            stays, along with its run history.
          </p>
        }
        confirmLabel="Remove key"
        busy={remove.isPending}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
          setRemoving(null);
        }}
      />
    </main>
  );
}
