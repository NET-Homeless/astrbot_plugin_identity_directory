<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Badge } from "$lib/components/ui/badge";
  import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
  } from "$lib/components/ui/table";
  import {
    Search,
    Link,
    Unlink,
    Trash2,
    KeyRound,
    ExternalLink,
    MessageSquare,
    ChevronLeft,
    ChevronRight,
  } from "lucide-svelte";
  import type { AccountView } from "$lib/types";

  let searchTimeout: number | null = null;
  let platformTimeout: number | null = null;
  let instanceTimeout: number | null = null;

  function handleSearchInput(e: Event) {
    const target = e.target as HTMLInputElement;
    directoryState.accountQuery = target.value;
    directoryState.accountPage = 1;
    if (searchTimeout !== null) clearTimeout(searchTimeout);
    searchTimeout = window.setTimeout(() => {
      directoryState.loadAccounts();
    }, 280);
  }

  function handlePlatformInput(e: Event) {
    const target = e.target as HTMLInputElement;
    directoryState.accountPlatform = target.value;
    directoryState.accountPage = 1;
    if (platformTimeout !== null) clearTimeout(platformTimeout);
    platformTimeout = window.setTimeout(() => {
      directoryState.loadAccounts();
    }, 280);
  }

  function handleInstanceInput(e: Event) {
    const target = e.target as HTMLInputElement;
    directoryState.accountInstance = target.value;
    directoryState.accountPage = 1;
    if (instanceTimeout !== null) clearTimeout(instanceTimeout);
    instanceTimeout = window.setTimeout(() => {
      directoryState.loadAccounts();
    }, 280);
  }

  const totalPages = $derived(
    Math.max(1, Math.ceil(directoryState.accountTotal / directoryState.accountPageSize))
  );

  function formatTime(timestamp: number): string {
    if (!timestamp) return "—";
    const d = new Date(timestamp * 1000);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function getPlatformBadgeClass(platform: string): string {
    const p = platform.toLowerCase();
    if (p.includes("qq") || p.includes("cqhttp")) {
      return "border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400";
    }
    if (p.includes("rocket") || p.includes("rc")) {
      return "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400";
    }
    if (p.includes("tg") || p.includes("telegram")) {
      return "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400";
    }
    if (p.includes("discord")) {
      return "border-indigo-500/30 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400";
    }
    return "border-muted bg-muted/60 text-muted-foreground";
  }

  function confirmDelete(account: AccountView) {
    if (window.confirm(`确定要从通讯录中删除账号 ${account.platform}:${account.platform_user_id} 吗？`)) {
      directoryState.deleteAccount(account.account_id);
    }
  }
</script>

<div class="flex flex-col gap-4">
  <!-- Toolbar -->
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-center gap-2 flex-1 max-w-3xl">
      <div class="relative min-w-[200px] flex-1">
        <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder="搜索账号 ID / 用户名…"
          value={directoryState.accountQuery}
          oninput={handleSearchInput}
          class="h-9 pl-9"
        />
      </div>

      <div class="w-44">
        <Input
          type="text"
          placeholder="平台 (如 aiocqhttp)"
          value={directoryState.accountPlatform}
          oninput={handlePlatformInput}
          class="h-9"
        />
      </div>

      <div class="w-44">
        <Input
          type="text"
          placeholder="平台实例 ID"
          value={directoryState.accountInstance}
          oninput={handleInstanceInput}
          class="h-9"
        />
      </div>
    </div>

    <div class="flex items-center gap-4">
      <label class="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
        <input
          type="checkbox"
          checked={directoryState.accountUnlinked}
          onchange={(e) => {
            directoryState.accountUnlinked = (e.target as HTMLInputElement).checked;
            directoryState.accountPage = 1;
            directoryState.loadAccounts();
          }}
          class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary dark:border-gray-700"
        />
        <span>只看未绑定</span>
      </label>
    </div>
  </div>

  <!-- Data Table -->
  <div class="rounded-xl border bg-card shadow-sm overflow-hidden">
    <Table class="table-fixed w-full">
      <TableHeader>
        <TableRow class="bg-muted/40">
          <TableHead class="w-[120px]">平台</TableHead>
          <TableHead class="w-[180px]">账号 ID</TableHead>
          <TableHead class="w-[140px]">用户名</TableHead>
          <TableHead class="w-[160px]">所属联系人</TableHead>
          <TableHead>群名片与别名</TableHead>
          <TableHead class="w-[150px]">最后活跃</TableHead>
          <TableHead class="w-[120px] text-right pr-4">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {#if directoryState.accounts.length === 0}
          <TableRow>
            <TableCell colspan={7} class="h-32 text-center text-muted-foreground">
              <div class="flex flex-col items-center justify-center gap-2">
                <KeyRound class="h-8 w-8 text-muted-foreground/50" />
                <p>暂无账号记录</p>
              </div>
            </TableCell>
          </TableRow>
        {:else}
          {#each directoryState.accounts as account (account.account_id)}
            <TableRow class="hover:bg-muted/30 transition-colors">
              <TableCell>
                <div class="flex min-w-0 flex-col items-start gap-1">
                  <Badge
                    variant="outline"
                    class={"max-w-[110px] px-2 py-0.5 text-[11px] font-medium " + getPlatformBadgeClass(account.platform)}
                  >
                    <span class="truncate">{account.platform}</span>
                  </Badge>
                  {#if account.platform_instance_id && account.platform_instance_id !== account.platform}
                    <code class="block max-w-[110px] truncate text-[10px] text-muted-foreground" title={account.platform_instance_id}>
                      {account.platform_instance_id}
                    </code>
                  {/if}
                </div>
              </TableCell>

              <TableCell>
                <code class="rounded bg-muted px-1.5 py-0.5 text-xs font-mono font-medium truncate block max-w-[160px]" title={account.platform_user_id}>
                  {account.platform_user_id}
                </code>
              </TableCell>

              <TableCell class="text-xs">
                {#if account.username}
                  <span class="font-medium text-foreground truncate block max-w-[130px]" title={"@" + account.username}>@{account.username}</span>
                {:else}
                  <span class="text-muted-foreground/50">—</span>
                {/if}
              </TableCell>

              <TableCell>
                {#if account.person_id}
                  <button
                    type="button"
                    onclick={() => directoryState.openPersonDetail(account.person_id!)}
                    class="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline truncate max-w-[140px]"
                    title={account.person_name || "查看关联联系人"}
                  >
                    <span class="truncate">{account.person_name || "查看关联联系人"}</span>
                    <ExternalLink class="h-3 w-3 shrink-0" />
                  </button>
                {:else}
                  <Badge variant="outline" class="border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400 text-[11px]">
                    未绑定
                  </Badge>
                {/if}
              </TableCell>

              <TableCell>
                <div class="flex flex-wrap items-center gap-1.5 max-h-16 overflow-hidden">
                  {#if account.memberships && account.memberships.length > 0}
                    {#each account.memberships.filter((m) => m.current_card) as m}
                      <span class="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground max-w-[180px] truncate">
                        <MessageSquare class="h-3 w-3 text-muted-foreground shrink-0" />
                        <strong class="font-medium truncate">{m.current_card}</strong>
                        <span class="text-[10px] text-muted-foreground shrink-0">@{m.group_id}</span>
                      </span>
                    {/each}
                  {/if}
                  {#if account.alias_count > 0}
                    <span class="text-[11px] text-muted-foreground shrink-0">
                      ({account.alias_count} 个别名历史)
                    </span>
                  {/if}
                  {#if (!account.memberships || account.memberships.length === 0) && account.alias_count === 0}
                    <span class="text-xs text-muted-foreground/50">—</span>
                  {/if}
                </div>
              </TableCell>

              <TableCell class="text-xs text-muted-foreground whitespace-nowrap">
                {formatTime(account.last_seen)}
              </TableCell>

              <TableCell class="text-right pr-4 whitespace-nowrap">
                <div class="flex items-center justify-end gap-1">
                  {#if account.person_id}
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={() => directoryState.unlinkAccount(account.account_id)}
                      class="h-7.5 px-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted"
                      title="解绑账号"
                    >
                      <Unlink class="h-3.5 w-3.5" />
                    </Button>
                  {:else}
                    <Button
                      variant="ghost"
                      size="sm"
                      onclick={() => directoryState.openLink(account)}
                      class="h-7.5 gap-1 px-2 text-xs text-primary hover:bg-primary/10"
                    >
                      <Link class="h-3.5 w-3.5" />
                      <span>绑定</span>
                    </Button>
                  {/if}

                  <Button
                    variant="ghost"
                    size="sm"
                    onclick={() => confirmDelete(account)}
                    class="h-7.5 px-2 text-xs text-destructive hover:bg-destructive/10"
                    title="删除账号"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          {/each}
        {/if}
      </TableBody>
    </Table>
  </div>

  <div class="flex items-center justify-between text-xs text-muted-foreground px-1">
    <span>
      共 <strong class="font-medium text-foreground">{directoryState.accountTotal}</strong> 个账号
    </span>

    <div class="flex items-center gap-2">
      <span>第 {directoryState.accountPage} / {totalPages} 页</span>
      <Button
        variant="outline"
        size="icon-sm"
        disabled={directoryState.accountPage <= 1}
        onclick={() => {
          directoryState.accountPage -= 1;
          directoryState.loadAccounts();
        }}
      >
        <ChevronLeft class="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        disabled={directoryState.accountPage >= totalPages}
        onclick={() => {
          directoryState.accountPage += 1;
          directoryState.loadAccounts();
        }}
      >
        <ChevronRight class="h-4 w-4" />
      </Button>
    </div>
  </div>
</div>
