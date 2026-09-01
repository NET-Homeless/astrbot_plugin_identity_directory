<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import {
    Users,
    KeyRound,
    UserX,
    MessageSquare,
    Tags,
    RefreshCw,
    Wrench,
    UserPlus,
  } from "lucide-svelte";
</script>

<header class="flex flex-col gap-4 border-b pb-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
        <Users class="h-5 w-5" />
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight">跨平台通讯录</h1>
        <p class="text-xs text-muted-foreground">身份解析与多账号归并中心</p>
      </div>
    </div>

    <div class="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onclick={() => directoryState.refreshAll()}
        disabled={directoryState.isLoading}
        class="h-9 gap-1.5"
      >
        <RefreshCw class={"h-3.5 w-3.5" + (directoryState.isLoading ? " animate-spin" : "")} />
        <span>刷新</span>
      </Button>

      {#if directoryState.stats.repairable_unlinked_accounts > 0}
        <Button
          variant="secondary"
          size="sm"
          onclick={() => directoryState.repairUnlinked()}
          class="h-9 gap-1.5 border border-amber-500/30 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
        >
          <Wrench class="h-3.5 w-3.5" />
          <span>修复未绑定 ({directoryState.stats.repairable_unlinked_accounts})</span>
        </Button>
      {/if}

      <Button
        size="sm"
        onclick={() => {
          directoryState.isCreatePersonOpen = true;
        }}
        class="h-9 gap-1.5 shadow-sm"
      >
        <UserPlus class="h-3.5 w-3.5" />
        <span>新建联系人</span>
      </Button>
    </div>
  </div>

  <!-- Stats Bar -->
  <div class="flex flex-wrap items-center gap-2 pt-1 text-xs">
    <Badge variant="outline" class="gap-1.5 py-1 px-2.5 font-normal">
      <Users class="h-3.5 w-3.5 text-blue-500" />
      <span>联系人:</span>
      <strong class="font-semibold">{directoryState.stats.persons}</strong>
    </Badge>

    <Badge variant="outline" class="gap-1.5 py-1 px-2.5 font-normal">
      <KeyRound class="h-3.5 w-3.5 text-emerald-500" />
      <span>平台账号:</span>
      <strong class="font-semibold">{directoryState.stats.accounts}</strong>
    </Badge>

    <Badge
      variant="outline"
      class={"gap-1.5 py-1 px-2.5 font-normal " +
        (directoryState.stats.unlinked_accounts > 0
          ? "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
          : "")}
    >
      <UserX class="h-3.5 w-3.5" />
      <span>未绑定账号:</span>
      <strong class="font-semibold">{directoryState.stats.unlinked_accounts}</strong>
    </Badge>

    <Badge variant="outline" class="gap-1.5 py-1 px-2.5 font-normal">
      <MessageSquare class="h-3.5 w-3.5 text-indigo-500" />
      <span>群成员关系:</span>
      <strong class="font-semibold">{directoryState.stats.memberships}</strong>
    </Badge>

    <Badge variant="outline" class="gap-1.5 py-1 px-2.5 font-normal">
      <Tags class="h-3.5 w-3.5 text-purple-500" />
      <span>显示名历史:</span>
      <strong class="font-semibold">{directoryState.stats.aliases}</strong>
    </Badge>
  </div>
</header>
