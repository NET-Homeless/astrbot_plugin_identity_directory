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
import { extractErrorMessage } from "$lib/utils";

interface ActionOptions<T> {
  loading?: (state: boolean) => void;
  errorMsg?: string;
  successMsg?: string | ((result: T) => string);
  onSuccess?: (result: T) => void | Promise<void>;
  silent?: boolean;
}

interface QueryOptions {
  loading?: (state: boolean) => void;
  errorMsg?: string;
  silent?: boolean;
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

  /**
   * Unified mutation execution runner:
   * 1. Automatically sets/resets loading state
   * 2. Handles success and error toasts
   * 3. Triggers onSuccess cascade refreshes
   * 4. Returns data on success, null on failure
   */
  async runAction<T>(action: () => Promise<T>, options: ActionOptions<T> = {}): Promise<T | null> {
    options.loading?.(true);
    try {
      const result = await action();
      if (options.successMsg) {
        const msg =
          typeof options.successMsg === "function"
            ? options.successMsg(result)
            : options.successMsg;
        this.showToast(msg, "success");
      }
      if (options.onSuccess) {
        await options.onSuccess(result);
      }
      return result;
    } catch (e: unknown) {
      if (!options.silent) {
        this.showToast(extractErrorMessage(e, options.errorMsg ?? "操作失败"), "error");
      }
      return null;
    } finally {
      options.loading?.(false);
    }
  }

  /**
   * Unified query execution runner:
   * 1. Automatically toggles loading state
   * 2. Safely falls back on errors with optional toast
   */
  async fetchQuery<T>(
    fetcher: () => Promise<T>,
    fallback: T,
    options: QueryOptions = {},
  ): Promise<T> {
    options.loading?.(true);
    try {
      return await fetcher();
    } catch (e: unknown) {
      if (!options.silent && options.errorMsg) {
        this.showToast(extractErrorMessage(e, options.errorMsg), "error");
      }
      return fallback;
    } finally {
      options.loading?.(false);
    }
  }

  // =========================================================================
  // Query Methods (Data fetching)
  // =========================================================================

  async loadStats() {
    this.stats = await this.fetchQuery(() => apiGet<DirectoryStats>("stats"), this.stats, {
      silent: true,
    });
  }

  async loadPersons() {
    const offset = (this.personPage - 1) * this.personPageSize;
    const res = await this.fetchQuery(
      () =>
        apiGet<PersonListResponse>("persons", {
          q: this.personQuery,
          archived: this.personArchived ? "1" : "0",
          limit: this.personPageSize,
          offset,
        }),
      { total: this.personTotal, items: this.persons },
      {
        loading: (v) => (this.isLoading = v),
        errorMsg: "加载联系人失败",
      },
    );
    this.persons = res.items;
    this.personTotal = res.total;
  }

  async loadAccounts() {
    const offset = (this.accountPage - 1) * this.accountPageSize;
    const res = await this.fetchQuery(
      () =>
        apiGet<AccountListResponse>("accounts", {
          q: this.accountQuery,
          platform: this.accountPlatform,
          platform_instance_id: this.accountInstance,
          unlinked: this.accountUnlinked ? "1" : "0",
          limit: this.accountPageSize,
          offset,
        }),
      { total: this.accountTotal, items: this.accounts },
      {
        loading: (v) => (this.isLoading = v),
        errorMsg: "加载账号列表失败",
      },
    );
    this.accounts = res.items;
    this.accountTotal = res.total;
  }

  async openPersonDetail(personId: string) {
    const requestVersion = ++this.detailRequestVersion;
    this.activePersonId = personId;
    this.isDetailOpen = true;

    await this.fetchQuery(
      async () => {
        const view = await apiGet<PersonView>(`persons/${personId}`);
        if (requestVersion !== this.detailRequestVersion || this.activePersonId !== personId)
          return null;
        this.activePersonView = view;

        const aliasPromises = view.accounts.map((a) =>
          apiGet<{ items: Alias[] }>(`accounts/${a.account_id}/aliases`),
        );
        const aliasResults = await Promise.all(aliasPromises);
        if (requestVersion !== this.detailRequestVersion || this.activePersonId !== personId)
          return null;
        this.activePersonAliases = aliasResults.flatMap((r) => r.items);
        return view;
      },
      null,
      {
        loading: (v) => {
          if (requestVersion === this.detailRequestVersion) this.isDetailLoading = v;
        },
        errorMsg: "获取联系人详情失败",
      },
    );
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

  // =========================================================================
  // Mutation Methods (State-changing actions)
  // =========================================================================

  async savePerson(personId: string, data: Partial<Person>) {
    await this.runAction(
      () => apiPost(`persons/${personId}/update`, data as Record<string, unknown>),
      {
        loading: (v) => (this.isSaving = v),
        successMsg: "已成功保存修改",
        errorMsg: "保存失败",
        onSuccess: async () => {
          this.closePersonDetail();
          await Promise.all([this.loadPersons(), this.loadStats()]);
        },
      },
    );
  }

  async deletePerson(personId: string) {
    await this.runAction(() => apiPost(`persons/${personId}/delete`, {}), {
      loading: (v) => (this.isDeleting = v),
      successMsg: "联系人已彻底删除",
      errorMsg: "删除失败",
      onSuccess: async () => {
        this.closePersonDetail();
        await Promise.all([this.loadPersons(), this.loadAccounts(), this.loadStats()]);
      },
    });
  }

  async createPerson(
    name: string,
    notes: string = "",
    tags: string[] = [],
  ): Promise<Person | null> {
    return await this.runAction(
      () =>
        apiPost<Person>("persons/create", {
          canonical_name: name,
          notes,
          tags,
        }),
      {
        successMsg: (res) => `已新建联系人【${res.canonical_name}】`,
        errorMsg: "新建联系人失败",
        onSuccess: async () => {
          this.isCreatePersonOpen = false;
          await Promise.all([this.loadPersons(), this.loadStats()]);
        },
      },
    );
  }

  // Multi-merge operations: Merge selected sources INTO target
  async openMerge(target: PersonView) {
    this.mergeTarget = target;
    this.selectedSources = [];
    this.mergeSearchQuery = "";
    this.mergeCandidates = [];
    this.isMergeOpen = true;
    await this.searchMergeCandidates("");
  }

  async openMergeFromList(personId: string) {
    await this.runAction(
      async () => {
        const view = await apiGet<PersonView>(`persons/${personId}`);
        await this.openMerge(view);
      },
      {
        errorMsg: "获取联系人信息失败",
      },
    );
  }

  async searchMergeCandidates(query: string) {
    this.mergeSearchQuery = query;
    const res = await this.fetchQuery(
      () =>
        apiGet<PersonListResponse>("persons", {
          q: query.trim(),
          limit: 15,
        }),
      { total: 0, items: [] },
      { silent: true },
    );
    this.mergeCandidates = res.items.filter((p) => p.person_id !== this.mergeTarget?.person_id);
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
    const sourceIds = this.selectedSources.map((s) => s.person_id);
    const targetName = this.mergeTarget.canonical_name;
    const count = this.selectedSources.length;

    await this.runAction(
      () =>
        apiPost("persons/merge", {
          target_person_id: this.mergeTarget?.person_id,
          source_person_ids: sourceIds,
        }),
      {
        loading: (v) => (this.isMerging = v),
        successMsg: `已成功将 ${count} 个联系人合并入【${targetName}】！`,
        errorMsg: "合并失败",
        onSuccess: async () => {
          this.isMergeOpen = false;
          this.selectedSources = [];
          if (this.activePersonId) {
            await this.openPersonDetail(this.activePersonId);
          }
          await Promise.all([this.loadPersons(), this.loadAccounts(), this.loadStats()]);
        },
      },
    );
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
    const res = await this.fetchQuery(
      () =>
        apiGet<PersonListResponse>("persons", {
          q: query.trim(),
          limit: 8,
        }),
      { total: 0, items: [] },
      { silent: true },
    );
    this.linkCandidates = res.items;
  }

  async linkAccountToPerson(personId: string) {
    if (!this.targetAccountForLink) return;
    const targetAccountId = this.targetAccountForLink.account_id;

    await this.runAction(
      () =>
        apiPost(`accounts/${targetAccountId}/link`, {
          person_id: personId,
        }),
      {
        successMsg: "账号绑定成功",
        errorMsg: "绑定失败",
        onSuccess: async () => {
          this.isLinkOpen = false;
          this.targetAccountForLink = null;
          await Promise.all([this.loadAccounts(), this.loadPersons(), this.loadStats()]);
        },
      },
    );
  }

  async unlinkAccount(accountId: string) {
    await this.runAction(() => apiPost(`accounts/${accountId}/unlink`, {}), {
      successMsg: "已解绑账号",
      errorMsg: "解绑失败",
      onSuccess: async () => {
        if (this.activePersonId) {
          await this.openPersonDetail(this.activePersonId);
        }
        await Promise.all([this.loadAccounts(), this.loadPersons(), this.loadStats()]);
      },
    });
  }

  async deleteAccount(accountId: string) {
    await this.runAction(() => apiPost(`accounts/${accountId}/delete`, {}), {
      successMsg: "账号已删除",
      errorMsg: "删除账号失败",
      onSuccess: async () => {
        if (this.activePersonId) {
          await this.openPersonDetail(this.activePersonId);
        }
        await Promise.all([this.loadAccounts(), this.loadPersons(), this.loadStats()]);
      },
    });
  }

  async addAlias(accountId: string, name: string, platform: string) {
    if (!name.trim()) return;
    await this.runAction(
      () =>
        apiPost(`accounts/${accountId}/aliases/add`, {
          name: name.trim(),
          platform,
        }),
      {
        successMsg: "别名添加成功",
        errorMsg: "添加别名失败",
        onSuccess: async () => {
          if (this.activePersonId) {
            await this.openPersonDetail(this.activePersonId);
          }
          await this.loadStats();
        },
      },
    );
  }

  async deleteAlias(aliasId: string) {
    await this.runAction(() => apiPost(`aliases/${aliasId}/delete`, {}), {
      successMsg: "别名已删除",
      errorMsg: "删除别名失败",
      onSuccess: async () => {
        if (this.activePersonId) {
          await this.openPersonDetail(this.activePersonId);
        }
        await this.loadStats();
      },
    });
  }

  async repairUnlinked() {
    await this.runAction(() => apiPost<{ repaired: number }>("repair", {}), {
      successMsg: (res) => `已成功修复并绑定 ${res.repaired} 个悬空账号`,
      errorMsg: "修复失败",
      onSuccess: async () => {
        await Promise.all([this.loadAccounts(), this.loadPersons(), this.loadStats()]);
      },
    });
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
