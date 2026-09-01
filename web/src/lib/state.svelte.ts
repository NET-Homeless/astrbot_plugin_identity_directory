import { apiGet, apiPost } from "$lib/bridge";
import type {
  AccountListResponse,
  AccountView,
  Alias,
  DirectoryStats,
  Person,
  PersonListResponse,
  PersonView,
} from "$lib/types";

function extractErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) {
    const msg = error.message;
    if (typeof msg === "string") return msg;
  }
  return fallback;
}

class DirectoryState {
  // Stats
  stats = $state<DirectoryStats>({
    persons: 0,
    accounts: 0,
    unlinked_accounts: 0,
    repairable_unlinked_accounts: 0,
    memberships: 0,
    aliases: 0,
  });

  // UI tabs & global loading
  activeTab = $state<"persons" | "accounts">("persons");
  isLoading = $state<boolean>(false);
  isMerging = $state<boolean>(false);
  isSaving = $state<boolean>(false);
  toastMessage = $state<string | null>(null);
  toastType = $state<"success" | "error" | "info">("success");
  private toastTimer: number | null = null;

  // Persons View State
  persons = $state<Person[]>([]);
  personTotal = $state<number>(0);
  personQuery = $state<string>("");
  personArchived = $state<boolean>(false);
  personPage = $state<number>(1);
  personPageSize = $state<number>(20);

  // Accounts View State
  accounts = $state<AccountView[]>([]);
  accountTotal = $state<number>(0);
  accountQuery = $state<string>("");
  accountPlatform = $state<string>("");
  accountInstance = $state<string>("");
  accountUnlinked = $state<boolean>(false);
  accountPage = $state<number>(1);
  accountPageSize = $state<number>(50);

  // Person Details Modal/Drawer State
  activePersonId = $state<string | null>(null);
  activePersonView = $state<PersonView | null>(null);
  activePersonAliases = $state<Alias[]>([]);
  isDetailOpen = $state<boolean>(false);
  isDetailLoading = $state<boolean>(false);
  isDeleteOpen = $state<boolean>(false);
  isDeleting = $state<boolean>(false);
  private detailRequestVersion = 0;

  // Merge Dialog State: Merging MULTIPLE selected source persons INTO the target person
  isMergeOpen = $state<boolean>(false);
  mergeTarget = $state<PersonView | null>(null); // The surviving target (current active person)
  selectedSources = $state<Person[]>([]); // Multiple sources to merge into target
  mergeSearchQuery = $state<string>("");
  mergeCandidates = $state<Person[]>([]);

  // Link Dialog State
  isLinkOpen = $state<boolean>(false);
  targetAccountForLink = $state<AccountView | null>(null);
  linkSearchQuery = $state<string>("");
  linkCandidates = $state<Person[]>([]);

  // Create Person Dialog
  isCreatePersonOpen = $state<boolean>(false);

  showToast(msg: string, type: "success" | "error" | "info" = "success") {
    this.toastMessage = msg;
    this.toastType = type;
    if (this.toastTimer !== null) clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => {
      this.toastMessage = null;
    }, 3000);
  }

  async loadStats() {
    try {
      this.stats = await apiGet<DirectoryStats>("stats");
    } catch (e: unknown) {
      console.error("Failed to load stats:", e);
    }
  }

  async loadPersons() {
    this.isLoading = true;
    try {
      const offset = (this.personPage - 1) * this.personPageSize;
      const res = await apiGet<PersonListResponse>("persons", {
        q: this.personQuery,
        archived: this.personArchived ? "1" : "0",
        limit: this.personPageSize,
        offset,
      });
      this.persons = res.items;
      this.personTotal = res.total;
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "加载联系人失败"), "error");
    } finally {
      this.isLoading = false;
    }
  }

  async loadAccounts() {
    this.isLoading = true;
    try {
      const offset = (this.accountPage - 1) * this.accountPageSize;
      const res = await apiGet<AccountListResponse>("accounts", {
        q: this.accountQuery,
        platform: this.accountPlatform,
        platform_instance_id: this.accountInstance,
        unlinked: this.accountUnlinked ? "1" : "0",
        limit: this.accountPageSize,
        offset,
      });
      this.accounts = res.items;
      this.accountTotal = res.total;
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "加载账号列表失败"), "error");
    } finally {
      this.isLoading = false;
    }
  }

  async openPersonDetail(personId: string) {
    const requestVersion = ++this.detailRequestVersion;
    this.activePersonId = personId;
    this.isDetailOpen = true;
    this.isDetailLoading = true;
    try {
      const view = await apiGet<PersonView>(`persons/${personId}`);
      if (requestVersion !== this.detailRequestVersion || this.activePersonId !== personId) return;
      this.activePersonView = view;
      // Load aliases for all linked accounts
      const aliasPromises = view.accounts.map((a) =>
        apiGet<{ items: Alias[] }>(`accounts/${a.account_id}/aliases`),
      );
      const aliasResults = await Promise.all(aliasPromises);
      if (requestVersion !== this.detailRequestVersion || this.activePersonId !== personId) return;
      this.activePersonAliases = aliasResults.flatMap((r) => r.items);
    } catch (e: unknown) {
      if (requestVersion !== this.detailRequestVersion) return;
      this.showToast(extractErrorMessage(e, "获取联系人详情失败"), "error");
      this.closePersonDetail();
    } finally {
      if (requestVersion === this.detailRequestVersion) this.isDetailLoading = false;
    }
  }

  closePersonDetail() {
    this.detailRequestVersion += 1;
    this.isDetailOpen = false;
    this.isDetailLoading = false;
    this.isDeleteOpen = false;
    this.activePersonId = null;
    this.activePersonView = null;
    this.activePersonAliases = [];
  }

  async savePerson(personId: string, data: Partial<Person>) {
    this.isSaving = true;
    try {
      await apiPost(`persons/${personId}/update`, data as Record<string, unknown>);
      this.showToast("已成功保存修改", "success");
      this.closePersonDetail();
      await this.loadPersons();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "保存失败"), "error");
    } finally {
      this.isSaving = false;
    }
  }

  async deletePerson(personId: string) {
    this.isDeleting = true;
    try {
      await apiPost(`persons/${personId}/delete`, {});
      this.showToast("联系人已彻底删除", "success");
      this.closePersonDetail();
      await this.loadPersons();
      await this.loadAccounts();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "删除失败"), "error");
    } finally {
      this.isDeleting = false;
    }
  }

  async createPerson(name: string, notes: string = "", tags: string[] = []) {
    try {
      const res = await apiPost<Person>("persons/create", {
        canonical_name: name,
        notes,
        tags,
      });
      this.showToast(`已新建联系人【${res.canonical_name}】`, "success");
      this.isCreatePersonOpen = false;
      await this.loadPersons();
      await this.loadStats();
      return res;
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "新建联系人失败"), "error");
      return null;
    }
  }

  // Multi-merge operations: Merge selected sources INTO target
  async openMerge(target: PersonView) {
    this.mergeTarget = target;
    this.selectedSources = [];
    this.mergeSearchQuery = "";
    this.mergeCandidates = [];
    this.isMergeOpen = true;
    this.searchMergeCandidates("");
  }

  // Open merge directly from list table without opening the drawer
  async openMergeFromList(personId: string) {
    try {
      const view = await apiGet<PersonView>(`persons/${personId}`);
      await this.openMerge(view);
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "获取联系人信息失败"), "error");
    }
  }

  async searchMergeCandidates(query: string) {
    this.mergeSearchQuery = query;
    try {
      const res = await apiGet<PersonListResponse>("persons", {
        q: query.trim(),
        limit: 15,
      });
      // Filter out the target person itself
      this.mergeCandidates = res.items.filter((p) => p.person_id !== this.mergeTarget?.person_id);
    } catch {
      this.mergeCandidates = [];
    }
  }

  toggleMergeSource(person: Person) {
    const exists = this.selectedSources.some((s) => s.person_id === person.person_id);
    if (exists) {
      this.selectedSources = this.selectedSources.filter((s) => s.person_id !== person.person_id);
    } else {
      this.selectedSources = [...this.selectedSources, person];
    }
  }

  removeMergeSource(personId: string) {
    this.selectedSources = this.selectedSources.filter((s) => s.person_id !== personId);
  }

  async executeMerge() {
    if (!this.mergeTarget || this.selectedSources.length === 0) return;
    this.isMerging = true;
    try {
      const sourceIds = this.selectedSources.map((s) => s.person_id);
      const targetName = this.mergeTarget.canonical_name;
      const count = this.selectedSources.length;

      await apiPost("persons/merge", {
        target_person_id: this.mergeTarget.person_id,
        source_person_ids: sourceIds,
      });

      // 1. Close dialog
      this.isMergeOpen = false;
      this.selectedSources = [];

      // 2. Show prominent toast
      this.showToast(`已成功将 ${count} 个联系人合并入【${targetName}】！`, "success");

      // 3. Immediately refresh current open drawer with updated accounts
      if (this.activePersonId) {
        await this.openPersonDetail(this.activePersonId);
      }
      await this.loadPersons();
      await this.loadAccounts();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "合并失败"), "error");
    } finally {
      this.isMerging = false;
    }
  }

  // Link operations
  openLink(account: AccountView) {
    this.targetAccountForLink = account;
    this.linkSearchQuery = "";
    this.linkCandidates = [];
    this.isLinkOpen = true;
  }

  async searchLinkTargets(query: string) {
    if (!query.trim()) {
      this.linkCandidates = [];
      return;
    }
    try {
      const res = await apiGet<PersonListResponse>("persons", {
        q: query.trim(),
        limit: 8,
      });
      this.linkCandidates = res.items;
    } catch {
      this.linkCandidates = [];
    }
  }

  async linkAccountToPerson(personId: string) {
    if (!this.targetAccountForLink) return;
    try {
      await apiPost(`accounts/${this.targetAccountForLink.account_id}/link`, {
        person_id: personId,
      });
      this.showToast("账号绑定成功", "success");
      this.isLinkOpen = false;
      this.targetAccountForLink = null;
      await this.loadAccounts();
      await this.loadPersons();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "绑定失败"), "error");
    }
  }

  async unlinkAccount(accountId: string) {
    try {
      await apiPost(`accounts/${accountId}/unlink`, {});
      this.showToast("已解绑账号", "success");
      if (this.activePersonId) {
        await this.openPersonDetail(this.activePersonId);
      }
      await this.loadAccounts();
      await this.loadPersons();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "解绑失败"), "error");
    }
  }

  async deleteAccount(accountId: string) {
    try {
      await apiPost(`accounts/${accountId}/delete`, {});
      this.showToast("账号已删除", "success");
      if (this.activePersonId) {
        await this.openPersonDetail(this.activePersonId);
      }
      await this.loadAccounts();
      await this.loadPersons();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "删除账号失败"), "error");
    }
  }

  async addAlias(accountId: string, name: string, platform: string) {
    if (!name.trim()) return;
    try {
      await apiPost(`accounts/${accountId}/aliases/add`, {
        name: name.trim(),
        platform,
      });
      this.showToast("别名添加成功", "success");
      if (this.activePersonId) {
        await this.openPersonDetail(this.activePersonId);
      }
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "添加别名失败"), "error");
    }
  }

  async deleteAlias(aliasId: string) {
    try {
      await apiPost(`aliases/${aliasId}/delete`, {});
      this.showToast("别名已删除", "success");
      if (this.activePersonId) {
        await this.openPersonDetail(this.activePersonId);
      }
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "删除别名失败"), "error");
    }
  }

  async repairUnlinked() {
    try {
      const res = await apiPost<{ repaired: number }>("repair", {});
      this.showToast(`已成功修复并绑定 ${res.repaired} 个悬空账号`, "success");
      await this.loadAccounts();
      await this.loadPersons();
      await this.loadStats();
    } catch (e: unknown) {
      this.showToast(extractErrorMessage(e, "修复失败"), "error");
    }
  }

  refreshAll() {
    this.loadStats();
    if (this.activeTab === "persons") {
      this.loadPersons();
    } else {
      this.loadAccounts();
    }
  }
}

export const directoryState = new DirectoryState();
