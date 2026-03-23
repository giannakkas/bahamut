"use client";

import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string | null;
}

interface WaitlistEntry {
  id: number;
  email: string;
  full_name: string;
  workspace_name: string;
  status: string;
  created_at: string;
}

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [waitlist, setWaitlist] = useState<WaitlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [formEmail, setFormEmail] = useState("");
  const [formName, setFormName] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState("viewer");
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState("");

  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  const loadUsers = async () => {
    try {
      const res = await fetch(`${apiBase()}/admin/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to load users");
      const data = await res.json();
      setUsers(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const loadWaitlist = async () => {
    try {
      const res = await fetch(`${apiBase()}/admin/waitlist`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setWaitlist(data);
      }
    } catch {}
  };

  const removeFromWaitlist = async (id: number, email: string) => {
    if (!confirm(`Remove ${email} from waitlist?`)) return;
    try {
      await fetch(`${apiBase()}/admin/waitlist/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      loadWaitlist();
    } catch {}
  };

  useEffect(() => {
    loadUsers();
    loadWaitlist();
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    setCreateMsg("");
    try {
      const res = await fetch(`${apiBase()}/admin/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          email: formEmail,
          password: formPassword,
          full_name: formName,
          role: formRole,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to create user");
      setCreateMsg(`User ${formEmail} created successfully`);
      setFormEmail("");
      setFormName("");
      setFormPassword("");
      setFormRole("viewer");
      setShowCreate(false);
      loadUsers();
    } catch (e: any) {
      setCreateMsg(e.message);
    } finally {
      setCreating(false);
    }
  };

  const handleDeactivate = async (userId: string, email: string) => {
    if (!confirm(`Deactivate user ${email}?`)) return;
    try {
      const res = await fetch(`${apiBase()}/admin/users/${userId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed");
      }
      loadUsers();
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="p-3 sm:p-6 max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-lg sm:text-xl font-bold text-bah-heading">User Management</h1>
          <p className="text-xs text-bah-muted mt-1">Create and manage admin panel users</p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-4 py-2 bg-bah-cyan/20 text-bah-cyan border border-bah-cyan/30 rounded-lg text-sm font-semibold hover:bg-bah-cyan/30 transition-colors w-fit"
        >
          {showCreate ? "Cancel" : "+ New User"}
        </button>
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-bah-heading mb-4">Create New User</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-bah-muted mb-1">Email</label>
              <input
                className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-sm text-bah-heading outline-none focus:border-bah-cyan/40"
                value={formEmail}
                onChange={(e) => setFormEmail(e.target.value)}
                placeholder="user@bahamut.ai"
              />
            </div>
            <div>
              <label className="block text-xs text-bah-muted mb-1">Full Name</label>
              <input
                className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-sm text-bah-heading outline-none focus:border-bah-cyan/40"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="John Doe"
              />
            </div>
            <div>
              <label className="block text-xs text-bah-muted mb-1">Password</label>
              <input
                type="password"
                className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-sm text-bah-heading outline-none focus:border-bah-cyan/40"
                value={formPassword}
                onChange={(e) => setFormPassword(e.target.value)}
                placeholder="••••••"
              />
            </div>
            <div>
              <label className="block text-xs text-bah-muted mb-1">Role</label>
              <select
                className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-sm text-bah-heading outline-none focus:border-bah-cyan/40"
                value={formRole}
                onChange={(e) => setFormRole(e.target.value)}
              >
                <option value="viewer">Viewer</option>
                <option value="trader">Trader</option>
                <option value="admin">Admin</option>
              </select>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={handleCreate}
              disabled={creating || !formEmail || !formPassword || !formName}
              className="px-5 py-2 bg-bah-cyan text-black rounded-lg text-sm font-semibold hover:bg-bah-cyan/80 disabled:opacity-40 transition-colors"
            >
              {creating ? "Creating..." : "Create User"}
            </button>
            {createMsg && (
              <span className={`text-xs ${createMsg.includes("success") ? "text-green-400" : "text-red-400"}`}>
                {createMsg}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Users Table */}
      {loading ? (
        <div className="text-sm text-bah-muted text-center py-10">Loading users...</div>
      ) : error ? (
        <div className="text-sm text-red-400 text-center py-10">{error}</div>
      ) : (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="border-b border-bah-border text-left text-xs text-bah-muted uppercase tracking-wider">
                <th className="px-3 sm:px-4 py-3">User</th>
                <th className="px-3 sm:px-4 py-3">Role</th>
                <th className="px-3 sm:px-4 py-3">Status</th>
                <th className="px-3 sm:px-4 py-3 hidden sm:table-cell">Last Login</th>
                <th className="px-3 sm:px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-bah-border/50 hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <div className="font-medium text-bah-heading">{u.full_name}</div>
                    <div className="text-xs text-bah-muted">{u.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase
                      ${u.role === "admin" ? "bg-purple-500/20 text-purple-400 border border-purple-500/30" :
                        u.role === "trader" ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30" :
                        "bg-gray-500/20 text-gray-400 border border-gray-500/30"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`flex items-center gap-1.5 text-xs ${u.is_active ? "text-green-400" : "text-red-400"}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-green-400" : "bg-red-400"}`} />
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-bah-muted">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active && (
                      <button
                        onClick={() => handleDeactivate(u.id, u.email)}
                        className="text-xs text-red-400 hover:text-red-300 transition-colors"
                      >
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          {users.length === 0 && (
            <div className="text-sm text-bah-muted text-center py-8">No users found</div>
          )}
        </div>
      )}

      {/* ═══ REGISTERED INTEREST (Waitlist) ═══ */}
      {waitlist.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-base font-bold text-bah-heading">Registered Interest</h2>
              <p className="text-xs text-bah-muted mt-0.5">{waitlist.length} trader{waitlist.length !== 1 ? "s" : ""} waiting for access</p>
            </div>
            <span className="px-2.5 py-1 text-[10px] font-semibold rounded-full bg-[#c9a84c]/15 text-[#c9a84c] border border-[#c9a84c]/30">
              {waitlist.length} PENDING
            </span>
          </div>
          <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[480px]">
                <thead>
                  <tr className="border-b border-bah-border text-left text-xs text-bah-muted uppercase tracking-wider">
                    <th className="px-4 py-3">Trader</th>
                    <th className="px-4 py-3">Workspace</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 hidden sm:table-cell">Registered</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {waitlist.map((w) => (
                    <tr key={w.id} className="border-b border-bah-border/50 hover:bg-white/[0.02]">
                      <td className="px-4 py-3">
                        <div className="font-medium text-bah-heading">{w.full_name}</div>
                        <div className="text-xs text-bah-muted">{w.email}</div>
                      </td>
                      <td className="px-4 py-3 text-xs text-bah-muted">
                        {w.workspace_name || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[#c9a84c]/15 text-[#c9a84c] border border-[#c9a84c]/30">
                          {w.status || "PENDING"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-bah-muted hidden sm:table-cell">
                        {w.created_at ? new Date(w.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => removeFromWaitlist(w.id, w.email)}
                          className="text-xs text-red-400 hover:text-red-300 transition-colors"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
