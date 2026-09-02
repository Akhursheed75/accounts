"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/shell";
import { Card, ErrorNote, Modal, Spinner, StatusBadge, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import type {
  Bank, BalanceComponent, City, MatchSettings, Permission, Role, Shop, SystemSettings, UserRow,
} from "@/lib/types";

const TABS = [
  { key: "shops", label: "Shops & cities", permission: "shop.read" },
  { key: "banks", label: "Banks & accounts", permission: "shop.read" },
  { key: "users", label: "Users & roles", permission: "user.manage" },
  { key: "matching", label: "Matching rules", permission: "reconciliation.read" },
  { key: "system", label: "System", permission: "accounting.read" },
] as const;

export default function SettingsPage() {
  const { can } = useAuth();
  const available = TABS.filter((tab) => can(tab.permission));
  const [tab, setTab] = useState(available[0]?.key ?? "shops");

  return (
    <>
      <PageHeader title="Settings" description="Reference data, users and how matching behaves." />

      <div className="mb-4 flex flex-wrap gap-1 border-b border-ink-200">
        {available.map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              tab === item.key
                ? "border-brand-600 font-medium text-brand-700"
                : "border-transparent text-ink-600 hover:text-ink-900"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "shops" && <ShopsTab />}
      {tab === "banks" && <BanksTab />}
      {tab === "users" && <UsersTab />}
      {tab === "matching" && <MatchingTab />}
      {tab === "system" && <SystemTab />}
    </>
  );
}

/* ------------------------------------------------------------------ shops */

function ShopsTab() {
  const { can } = useAuth();
  const toast = useToast();
  const shops = useApi(() => api.get<Shop[]>("/shops", { include_inactive: true }), []);
  const cities = useApi(() => api.get<City[]>("/cities"), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", city_id: "" });
  const [cityName, setCityName] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function createShop(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/shops", {
        code: form.code.toUpperCase(),
        name: form.name,
        city_id: form.city_id ? Number(form.city_id) : null,
      });
      toast.push("ok", "Shop created.");
      setOpen(false);
      setForm({ code: "", name: "", city_id: "" });
      shops.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function toggleActive(shop: Shop) {
    try {
      await api.patch(`/shops/${shop.id}`, { is_active: !shop.is_active });
      shops.reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not update the shop.");
    }
  }

  async function addCity(event: React.FormEvent) {
    event.preventDefault();
    if (!cityName.trim()) return;
    try {
      await api.post("/cities", { name: cityName.trim() });
      setCityName("");
      cities.reload();
      toast.push("ok", "City added.");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not add the city.");
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card
        className="lg:col-span-2"
        title="Shops"
        description="New shops can be added at any time; nothing in the system assumes there are three."
        actions={
          can("shop.manage") && (
            <button className="btn-secondary btn-sm" onClick={() => setOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> Add shop
            </button>
          )
        }
        padded={false}
      >
        {shops.loading && !shops.data && <div className="p-5"><Spinner /></div>}
        <div className="table-scroll">
          <table className="w-full">
            <thead className="border-b border-ink-200 bg-ink-50">
              <tr>
                <th className="th">Code</th>
                <th className="th">Name</th>
                <th className="th">City</th>
                <th className="th">Status</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {(shops.data ?? []).map((shop) => (
                <tr key={shop.id}>
                  <td className="td font-mono text-xs">{shop.code}</td>
                  <td className="td font-medium">{shop.name}</td>
                  <td className="td">{shop.city_name ?? "—"}</td>
                  <td className="td">
                    <StatusBadge status={shop.is_active ? "ACTIVE" : "INACTIVE"} dot={false} />
                  </td>
                  <td className="td text-right">
                    {can("shop.manage") && (
                      <button className="btn-secondary btn-sm" onClick={() => toggleActive(shop)}>
                        {shop.is_active ? "Deactivate" : "Activate"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Cities">
        <ul className="mb-3 space-y-1 text-sm">
          {(cities.data ?? []).map((city) => (
            <li key={city.id} className="flex justify-between border-b border-ink-100 py-1">
              <span>{city.name}</span>
              <span className="text-xs text-ink-500">{city.country}</span>
            </li>
          ))}
        </ul>
        {can("shop.manage") && (
          <form onSubmit={addCity} className="flex gap-2">
            <input
              className="input"
              value={cityName}
              onChange={(e) => setCityName(e.target.value)}
              placeholder="New city"
            />
            <button className="btn-secondary btn-sm" type="submit">Add</button>
          </form>
        )}
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add a shop"
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn-primary btn-sm" form="shop-form" type="submit">Create</button>
          </>
        }
      >
        <form id="shop-form" onSubmit={createShop} className="space-y-3">
          <label className="block">
            <span className="label">Code</span>
            <input className="input" value={form.code} required
              onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="SHOP4" />
          </label>
          <label className="block">
            <span className="label">Name</span>
            <input className="input" value={form.name} required
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">City</span>
            <select className="input" value={form.city_id}
              onChange={(e) => setForm({ ...form, city_id: e.target.value })}>
              <option value="">No city</option>
              {(cities.data ?? []).map((city) => (
                <option key={city.id} value={city.id}>{city.name}</option>
              ))}
            </select>
          </label>
          <ErrorNote error={error} />
        </form>
      </Modal>
    </div>
  );
}

/* ------------------------------------------------------------------ banks */

function BanksTab() {
  const { can } = useAuth();
  const toast = useToast();
  const banks = useApi(() => api.get<Bank[]>("/banks", { include_inactive: true }), []);
  const parsers = useApi(() => api.get<string[]>("/banks/parsers"), []);
  const [bankOpen, setBankOpen] = useState(false);
  const [accountFor, setAccountFor] = useState<Bank | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [bankForm, setBankForm] = useState({ code: "", name: "", parser_key: "" });
  const [accountForm, setAccountForm] = useState({ label: "", account_number: "", currency_code: "USD" });

  async function createBank(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/banks", {
        code: bankForm.code.toUpperCase(),
        name: bankForm.name,
        parser_key: bankForm.parser_key || null,
      });
      toast.push("ok", "Bank created.");
      setBankOpen(false);
      setBankForm({ code: "", name: "", parser_key: "" });
      banks.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function createAccount(event: React.FormEvent) {
    event.preventDefault();
    if (!accountFor) return;
    setError(null);
    try {
      await api.post("/bank-accounts", { bank_id: accountFor.id, ...accountForm });
      toast.push("ok", "Account added.");
      setAccountFor(null);
      setAccountForm({ label: "", account_number: "", currency_code: "USD" });
      banks.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can("bank.manage") && (
          <button className="btn-secondary btn-sm" onClick={() => setBankOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> Add bank
          </button>
        )}
      </div>

      {banks.loading && !banks.data && <Spinner />}

      {(banks.data ?? []).map((bank) => (
        <Card
          key={bank.id}
          title={`${bank.code} — ${bank.name}`}
          description={
            bank.parser_available
              ? `Statements are read by the ${bank.parser_key} parser.`
              : "No statement parser is available for this bank yet. Uploads are stored and reported honestly rather than guessed at."
          }
          actions={
            can("bank.manage") && (
              <button className="btn-secondary btn-sm" onClick={() => setAccountFor(bank)}>
                <Plus className="h-3.5 w-3.5" /> Add account
              </button>
            )
          }
          padded={false}
        >
          <div className="table-scroll">
            <table className="w-full">
              <thead className="border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th">Account</th>
                  <th className="th">Number</th>
                  <th className="th">Currency</th>
                  <th className="th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {bank.accounts.length === 0 && (
                  <tr><td className="td text-ink-500" colSpan={4}>No accounts yet.</td></tr>
                )}
                {bank.accounts.map((account) => (
                  <tr key={account.id}>
                    <td className="td font-medium">{account.label}</td>
                    <td className="td font-mono text-xs">{account.account_number}</td>
                    <td className="td">{account.currency_code}</td>
                    <td className="td">
                      <StatusBadge status={account.is_active ? "ACTIVE" : "INACTIVE"} dot={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <Modal
        open={bankOpen}
        onClose={() => setBankOpen(false)}
        title="Add a bank"
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setBankOpen(false)}>Cancel</button>
            <button className="btn-primary btn-sm" form="bank-form" type="submit">Create</button>
          </>
        }
      >
        <form id="bank-form" onSubmit={createBank} className="space-y-3">
          <label className="block">
            <span className="label">Code</span>
            <input className="input" value={bankForm.code} required
              onChange={(e) => setBankForm({ ...bankForm, code: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">Name</span>
            <input className="input" value={bankForm.name} required
              onChange={(e) => setBankForm({ ...bankForm, name: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">Statement parser</span>
            <select className="input" value={bankForm.parser_key}
              onChange={(e) => setBankForm({ ...bankForm, parser_key: e.target.value })}>
              <option value="">Detect automatically</option>
              {(parsers.data ?? []).map((key) => (
                <option key={key} value={key}>{key}</option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-ink-500">
              A parser can be added later once a sample statement is available.
            </span>
          </label>
          <ErrorNote error={error} />
        </form>
      </Modal>

      <Modal
        open={Boolean(accountFor)}
        onClose={() => setAccountFor(null)}
        title={accountFor ? `Add an account to ${accountFor.code}` : "Add account"}
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setAccountFor(null)}>Cancel</button>
            <button className="btn-primary btn-sm" form="account-form" type="submit">Create</button>
          </>
        }
      >
        <form id="account-form" onSubmit={createAccount} className="space-y-3">
          <label className="block">
            <span className="label">Label</span>
            <input className="input" value={accountForm.label} required
              onChange={(e) => setAccountForm({ ...accountForm, label: e.target.value })}
              placeholder="BAC Cordobas" />
          </label>
          <label className="block">
            <span className="label">Account number</span>
            <input className="input" value={accountForm.account_number} required
              onChange={(e) => setAccountForm({ ...accountForm, account_number: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">Currency</span>
            <select className="input" value={accountForm.currency_code}
              onChange={(e) => setAccountForm({ ...accountForm, currency_code: e.target.value })}>
              <option value="USD">USD $</option>
              <option value="NIO">Cordoba C$</option>
            </select>
            <span className="mt-1 block text-xs text-ink-500">
              One account per currency. The currency cannot be changed once transactions exist.
            </span>
          </label>
          <ErrorNote error={error} />
        </form>
      </Modal>
    </div>
  );
}

/* ------------------------------------------------------------------ users */

function UsersTab() {
  const toast = useToast();
  const users = useApi(() => api.get<UserRow[]>("/users"), []);
  const roles = useApi(() => api.get<Role[]>("/roles"), []);
  const shops = useApi(() => api.get<Shop[]>("/shops", { include_inactive: true }), []);
  const permissions = useApi(() => api.get<Permission[]>("/permissions"), []);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [form, setForm] = useState({
    email: "", full_name: "", password: "", role_id: "", shop_ids: [] as number[],
  });
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [rolePerms, setRolePerms] = useState<string[]>([]);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/users", {
        email: form.email,
        full_name: form.full_name,
        password: form.password,
        role_id: Number(form.role_id),
        shop_ids: form.shop_ids,
      });
      toast.push("ok", "User created.");
      setOpen(false);
      setForm({ email: "", full_name: "", password: "", role_id: "", shop_ids: [] });
      users.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function saveRole() {
    if (!editingRole) return;
    try {
      await api.put(`/roles/${editingRole.id}/permissions`, { permissions: rolePerms });
      toast.push("ok", "Permissions updated.");
      setEditingRole(null);
      roles.reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not save the role.");
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="Users"
        actions={
          <button className="btn-secondary btn-sm" onClick={() => setOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> Add user
          </button>
        }
        padded={false}
      >
        {users.loading && !users.data && <div className="p-5"><Spinner /></div>}
        <div className="table-scroll">
          <table className="w-full">
            <thead className="border-b border-ink-200 bg-ink-50">
              <tr>
                <th className="th">Name</th>
                <th className="th">Email</th>
                <th className="th">Role</th>
                <th className="th">Shops</th>
                <th className="th">Status</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {(users.data ?? []).map((user) => (
                <tr key={user.id}>
                  <td className="td font-medium">{user.full_name}</td>
                  <td className="td">{user.email}</td>
                  <td className="td">{user.role_name}</td>
                  <td className="td text-xs">
                    {user.shop_ids.length === 0
                      ? "All (role-wide)"
                      : user.shop_ids
                          .map((id) => (shops.data ?? []).find((s) => s.id === id)?.code ?? id)
                          .join(", ")}
                  </td>
                  <td className="td">
                    <StatusBadge status={user.is_active ? "ACTIVE" : "INACTIVE"} dot={false} />
                  </td>
                  <td className="td text-right">
                    <button
                      className="btn-secondary btn-sm"
                      onClick={async () => {
                        try {
                          await api.patch(`/users/${user.id}`, { is_active: !user.is_active });
                          users.reload();
                        } catch (err) {
                          toast.push("error", err instanceof Error ? err.message : "Failed.");
                        }
                      }}
                    >
                      {user.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Roles" description="Permissions are data, so new roles can be added without a code change.">
        <div className="space-y-2">
          {(roles.data ?? []).map((role) => (
            <div key={role.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-200 p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {role.name}{" "}
                  <span className="font-mono text-xs text-ink-500">({role.code})</span>
                </p>
                <p className="text-xs text-ink-500">
                  {role.description} · {role.permissions.length} permission(s) · {role.user_count} user(s)
                </p>
              </div>
              <button
                className="btn-secondary btn-sm"
                onClick={() => {
                  setEditingRole(role);
                  setRolePerms(role.permissions);
                }}
              >
                Edit permissions
              </button>
            </div>
          ))}
        </div>
      </Card>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add a user"
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn-primary btn-sm" form="user-form" type="submit">Create</button>
          </>
        }
      >
        <form id="user-form" onSubmit={createUser} className="space-y-3">
          <label className="block">
            <span className="label">Full name</span>
            <input className="input" value={form.full_name} required
              onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">Email</span>
            <input className="input" type="email" value={form.email} required
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label className="block">
            <span className="label">Password</span>
            <input className="input" type="text" value={form.password} required minLength={10}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <span className="mt-1 block text-xs text-ink-500">
              At least 10 characters. The user should change it after signing in.
            </span>
          </label>
          <label className="block">
            <span className="label">Role</span>
            <select className="input" value={form.role_id} required
              onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
              <option value="">Choose a role…</option>
              {(roles.data ?? []).map((role) => (
                <option key={role.id} value={role.id}>{role.name}</option>
              ))}
            </select>
          </label>
          <div>
            <span className="label">Shops this user may work with</span>
            <div className="space-y-1">
              {(shops.data ?? []).map((shop) => (
                <label key={shop.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.shop_ids.includes(shop.id)}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        shop_ids: e.target.checked
                          ? [...form.shop_ids, shop.id]
                          : form.shop_ids.filter((id) => id !== shop.id),
                      })
                    }
                  />
                  {shop.name}
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-ink-500">
              Roles with dashboard access see every shop regardless of this list.
            </p>
          </div>
          <ErrorNote error={error} />
        </form>
      </Modal>

      <Modal
        open={Boolean(editingRole)}
        onClose={() => setEditingRole(null)}
        wide
        title={editingRole ? `Permissions for ${editingRole.name}` : "Permissions"}
        footer={
          <>
            <button className="btn-secondary btn-sm" onClick={() => setEditingRole(null)}>Cancel</button>
            <button className="btn-primary btn-sm" onClick={saveRole}>Save</button>
          </>
        }
      >
        <div className="grid gap-1.5 sm:grid-cols-2">
          {(permissions.data ?? []).map((permission) => (
            <label key={permission.id} className="flex items-start gap-2 rounded p-1.5 text-sm hover:bg-ink-50">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={rolePerms.includes(permission.code)}
                onChange={(e) =>
                  setRolePerms((current) =>
                    e.target.checked
                      ? [...current, permission.code]
                      : current.filter((code) => code !== permission.code),
                  )
                }
              />
              <span>
                <span className="font-mono text-xs">{permission.code}</span>
                <span className="block text-xs text-ink-500">{permission.description}</span>
              </span>
            </label>
          ))}
        </div>
      </Modal>
    </div>
  );
}

/* --------------------------------------------------------------- matching */

function MatchingTab() {
  const { can } = useAuth();
  const toast = useToast();
  const { data, loading, reload } = useApi(() => api.get<MatchSettings>("/settings/matching"), []);
  const [draft, setDraft] = useState<MatchSettings | null>(null);
  const [error, setError] = useState<unknown>(null);
  const current = draft ?? data;

  async function save() {
    if (!current) return;
    setError(null);
    try {
      await api.put("/settings/matching", current);
      toast.push("ok", "Matching rules saved.");
      setDraft(null);
      reload();
    } catch (err) {
      setError(err);
    }
  }

  if (loading && !current) return <Spinner />;
  if (!current) return null;

  return (
    <Card
      title="Matching rules"
      description="Currency and bank are always required. Only the date window and the score thresholds are adjustable."
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="label">Date window (days)</span>
          <input
            type="number" min={0} max={30} className="input tabular"
            value={current.date_window_days}
            disabled={!can("settings.manage")}
            onChange={(e) => setDraft({ ...current, date_window_days: Number(e.target.value) })}
          />
          <span className="mt-1 block text-xs text-ink-500">
            How many days a bank transaction may differ from the sheet date.
          </span>
        </label>
        <label className="block">
          <span className="label">Amount tolerance</span>
          <input
            className="input tabular" inputMode="decimal"
            value={current.amount_tolerance}
            disabled={!can("settings.manage")}
            onChange={(e) => setDraft({ ...current, amount_tolerance: e.target.value })}
          />
          <span className="mt-1 block text-xs text-ink-500">
            Leave at 0.00 to require the amount to match exactly.
          </span>
        </label>
        <label className="block">
          <span className="label">Automatic match at or above</span>
          <input
            type="number" min={50} max={100} className="input tabular"
            value={current.auto_confirm_score}
            disabled={!can("settings.manage")}
            onChange={(e) => setDraft({ ...current, auto_confirm_score: Number(e.target.value) })}
          />
        </label>
        <label className="block">
          <span className="label">Suggest at or above</span>
          <input
            type="number" min={0} max={100} className="input tabular"
            value={current.suggest_score}
            disabled={!can("settings.manage")}
            onChange={(e) => setDraft({ ...current, suggest_score: Number(e.target.value) })}
          />
        </label>
      </div>

      <div className="mt-4 space-y-2">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox" className="mt-0.5"
            checked={current.auto_confirm_requires_unique}
            disabled={!can("settings.manage")}
            onChange={(e) =>
              setDraft({ ...current, auto_confirm_requires_unique: e.target.checked })
            }
          />
          <span>
            Never match automatically when more than one transaction is equally good
            <span className="block text-xs text-ink-500">
              Strongly recommended. Two identical deposits on one day are ordinary; picking one at
              random would reconcile the wrong money.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox" className="mt-0.5"
            checked={current.match_debit_transactions}
            disabled={!can("settings.manage")}
            onChange={(e) => setDraft({ ...current, match_debit_transactions: e.target.checked })}
          />
          <span>
            Also consider outgoing transactions
            <span className="block text-xs text-ink-500">
              Off by default: shop payments are money coming in.
            </span>
          </span>
        </label>
      </div>

      <ErrorNote error={error} />

      {can("settings.manage") && (
        <div className="mt-4 flex gap-2">
          <button className="btn-primary btn-sm" onClick={save} disabled={!draft}>Save</button>
          {draft && (
            <button className="btn-secondary btn-sm" onClick={() => setDraft(null)}>Discard</button>
          )}
        </div>
      )}
    </Card>
  );
}

/* ----------------------------------------------------------------- system */

function SystemTab() {
  const { can } = useAuth();
  const toast = useToast();
  const { data, loading, reload } = useApi(() => api.get<SystemSettings>("/settings/system"), []);
  const [draft, setDraft] = useState<SystemSettings | null>(null);
  const [error, setError] = useState<unknown>(null);
  const current = draft ?? data;

  async function save() {
    if (!current) return;
    setError(null);
    try {
      await api.put("/settings/system", current);
      toast.push("ok", "Settings saved.");
      setDraft(null);
      reload();
    } catch (err) {
      setError(err);
    }
  }

  function updateComponent(index: number, patch: Partial<BalanceComponent>) {
    if (!current) return;
    const components = current.balance_components.map((component, i) =>
      i === index ? { ...component, ...patch } : component,
    );
    setDraft({ ...current, balance_components: components });
  }

  if (loading && !current) return <Spinner />;
  if (!current) return null;

  return (
    <div className="space-y-4">
      <Card title="Company">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="label">Company name</span>
            <input
              className="input" value={current.company_name}
              disabled={!can("settings.manage")}
              onChange={(e) => setDraft({ ...current, company_name: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="label">Reporting currency shown first</span>
            <select
              className="input" value={current.base_currency}
              disabled={!can("settings.manage")}
              onChange={(e) => setDraft({ ...current, base_currency: e.target.value })}
            >
              <option value="USD">USD $</option>
              <option value="NIO">Cordoba C$</option>
            </select>
            <span className="mt-1 block text-xs text-ink-500">
              Presentation only. Balances are always kept separately per currency.
            </span>
          </label>
        </div>
      </Card>

      <Card
        title="Closing balance formula"
        description="Which parts of the sheet feed the closing balance, and whether they add or subtract."
      >
        <div className="space-y-2">
          {current.balance_components.map((component, index) => (
            <div
              key={component.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-200 p-2.5"
            >
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox" checked={component.enabled}
                  disabled={!can("settings.manage")}
                  onChange={(e) => updateComponent(index, { enabled: e.target.checked })}
                />
                {component.label}
                <span className="font-mono text-xs text-ink-400">{component.key}</span>
              </label>
              <select
                className="input h-8 w-28 text-xs"
                value={component.sign}
                disabled={!can("settings.manage") || !component.enabled}
                onChange={(e) => updateComponent(index, { sign: Number(e.target.value) })}
              >
                <option value={1}>Adds (+)</option>
                <option value={-1}>Subtracts (−)</option>
                <option value={0}>Not used</option>
              </select>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-500">
          Every saved sheet shows the calculation step by step using exactly these components.
        </p>
      </Card>

      <ErrorNote error={error} />

      {can("settings.manage") && (
        <div className="flex gap-2">
          <button className="btn-primary btn-sm" onClick={save} disabled={!draft}>Save</button>
          {draft && <button className="btn-secondary btn-sm" onClick={() => setDraft(null)}>Discard</button>}
        </div>
      )}
    </div>
  );
}
