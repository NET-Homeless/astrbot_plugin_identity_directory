<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Badge } from "$lib/components/ui/badge";
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
  } from "$lib/components/ui/dialog";
  import {
    GitMerge,
    Search,
    AlertTriangle,
    X,
    UserCheck,
    Users,
    Loader2,
  } from "lucide-svelte";
  import type { Person } from "$lib/types";

  let searchTimeout: number | null = null;

  function handleSearch(e: Event) {
    const query = (e.target as HTMLInputElement).value;
    if (searchTimeout !== null) clearTimeout(searchTimeout);
    searchTimeout = window.setTimeout(() => {
      directoryState.searchMergeCandidates(query);
    }, 250);
  }

  function isSelected(personId: string): boolean {
    return directoryState.selectedSources.some((s) => s.person_id === personId);
  }

  function handleToggle(candidate: Person) {
    if (directoryState.isMerging) return;
    directoryState.toggleMergeSource(candidate);
  }
</script>

<Dialog
  open={directoryState.isMergeOpen}
  onOpenChange={(open) => {
    if (directoryState.isMerging) return; // Prevent closing while merging
    directoryState.isMergeOpen = open;
    if (!open) {
      directoryState.mergeTarget = null;
      directoryState.selectedSources = [];
      directoryState.mergeCandidates = [];
      directoryState.mergeSearchQuery = "";
    }
  }}
>
  <DialogContent
    class="h-[calc(100dvh-2rem)] max-h-[760px] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0"
  >
    <DialogHeader class="min-w-0 border-b px-5 pb-4 pt-5 pr-12">
      <DialogTitle class="flex min-w-0 items-start gap-2 text-base font-semibold">
        <GitMerge class="mt-0.5 h-5 w-5 shrink-0 text-purple-500" />
        <span class="min-w-0 [overflow-wrap:anywhere]">合并联系人进【{directoryState.mergeTarget?.canonical_name || "—"}】</span>
      </DialogTitle>
    </DialogHeader>

    {#if directoryState.mergeTarget}
      <div
        data-merge-scroll-body
        class="flex min-h-0 min-w-0 flex-col gap-4 overflow-x-hidden overflow-y-auto overscroll-contain px-5 py-4"
      >
        <!-- Target Info Banner -->
        <div class="flex min-w-0 flex-col gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3.5 text-xs sm:flex-row sm:items-center sm:justify-between">
          <div class="flex min-w-0 items-start gap-2">
            <UserCheck class="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div class="min-w-0 [overflow-wrap:anywhere]">
              <span class="text-muted-foreground">当前合并主体（保留）：</span>
              <strong class="ml-1 text-sm font-bold text-foreground">{directoryState.mergeTarget.canonical_name}</strong>
            </div>
          </div>
          <span class="shrink-0 font-mono text-[11px] text-muted-foreground">
            现有 {directoryState.mergeTarget.accounts.length} 个账号
          </span>
        </div>

        <!-- Selected Tags Bar -->
        {#if directoryState.selectedSources.length > 0}
          <div class="flex flex-col gap-2 rounded-xl border bg-muted/40 p-3">
            <div class="flex items-center justify-between text-xs font-semibold text-foreground">
              <span>已勾选 {directoryState.selectedSources.length} 个待合并联系人：</span>
              <button
                type="button"
                disabled={directoryState.isMerging}
                onclick={() => (directoryState.selectedSources = [])}
                class="text-[11px] text-muted-foreground hover:text-destructive disabled:opacity-50"
              >
                清空选择
              </button>
            </div>

            <div class="flex flex-wrap gap-1.5 pt-1">
              {#each directoryState.selectedSources as src (src.person_id)}
                <Badge
                  variant="secondary"
                  data-selected-source-badge
                  class="h-auto max-w-full min-w-0 shrink items-start gap-1.5 whitespace-normal px-2.5 py-1 text-left text-xs font-medium"
                >
                  <span class="min-w-0 [overflow-wrap:anywhere]">{src.canonical_name}</span>
                  <button
                    type="button"
                    disabled={directoryState.isMerging}
                    onclick={() => directoryState.removeMergeSource(src.person_id)}
                    class="shrink-0 self-start text-muted-foreground hover:text-destructive disabled:opacity-50"
                    title="移除"
                  >
                    <X class="h-3 w-3" />
                  </button>
                </Badge>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Search Input -->
        <div class="relative">
          <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            disabled={directoryState.isMerging}
            placeholder="搜索待合并的联系人姓名或备注画像…"
            value={directoryState.mergeSearchQuery}
            oninput={handleSearch}
            class="h-9 pl-9"
          />
        </div>

        <!-- Multi-select Candidates List -->
        <div class="flex flex-col gap-1.5 max-h-64 overflow-y-auto pr-1">
          {#if directoryState.mergeCandidates.length === 0}
            <div class="rounded-xl border border-dashed py-8 text-center text-xs text-muted-foreground">
              <div class="flex flex-col items-center justify-center gap-1.5">
                <Users class="h-6 w-6 text-muted-foreground/40" />
                <span>未找到可合并的联系人</span>
              </div>
            </div>
          {:else}
            {#each directoryState.mergeCandidates as candidate (candidate.person_id)}
              {@const selected = isSelected(candidate.person_id)}
              <div
                data-merge-candidate
                role="button"
                tabindex="0"
                onclick={() => handleToggle(candidate)}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleToggle(candidate);
                  }
                }}
                class={"flex min-w-0 shrink-0 items-center gap-3 overflow-x-hidden rounded-xl border p-3 text-left transition-all cursor-pointer select-none " +
                  (selected
                    ? "border-primary bg-primary/5 shadow-xs"
                    : "border-border bg-card hover:bg-muted/40")}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={directoryState.isMerging}
                  onclick={(e) => e.stopPropagation()}
                  onchange={() => handleToggle(candidate)}
                  class="h-4 w-4 shrink-0 rounded border-gray-300 text-primary focus:ring-primary dark:border-gray-700"
                />

                <div class="flex-1 min-w-0">
                  <div class="flex min-w-0 items-start gap-2">
                    <span class="min-w-0 text-sm font-semibold text-foreground [overflow-wrap:anywhere]">{candidate.canonical_name}</span>
                    {#if candidate.is_bot}
                      <Badge variant="secondary" class="text-[10px] px-1.5 py-0">Bot</Badge>
                    {/if}
                  </div>
                  {#if candidate.notes}
                    <p class="line-clamp-1 text-xs text-muted-foreground mt-0.5 font-normal">
                      {candidate.notes}
                    </p>
                  {/if}
                </div>
              </div>
            {/each}
          {/if}
        </div>

        {#if directoryState.selectedSources.length > 0}
          <div class="flex min-w-0 items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
            <AlertTriangle class="h-4 w-4 shrink-0 mt-0.5" />
            <div class="min-w-0 [overflow-wrap:anywhere]">
              <strong>不可逆合并：</strong>所选的 <strong>{directoryState.selectedSources.length}</strong> 个联系人的全部账号（含群名片与别名）将全部转移至【<strong>{directoryState.mergeTarget.canonical_name}</strong>】名下，被合并的原联系人将被彻底删除。
            </div>
          </div>
        {/if}
      </div>
      <DialogFooter
        data-merge-footer
        class="mx-0 mb-0 shrink-0 grid grid-cols-1 rounded-t-none rounded-b-xl border-t bg-card px-5 py-4 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center sm:justify-between"
      >
        <Button
          variant="outline"
          size="sm"
          disabled={directoryState.isMerging}
          class="w-full sm:w-auto"
          onclick={() => {
            directoryState.isMergeOpen = false;
          }}
        >
          取消
        </Button>

        <Button
          variant="destructive"
          size="sm"
          disabled={directoryState.selectedSources.length === 0 || directoryState.isMerging}
          data-merge-confirm
          onclick={() => {
            void directoryState.executeMerge();
          }}
          class="w-full min-w-0 max-w-full gap-1.5 whitespace-normal text-center font-semibold sm:w-auto"
        >
          {#if directoryState.isMerging}
            <Loader2 class="h-4 w-4 animate-spin" />
            <span class="min-w-0 [overflow-wrap:anywhere]">正在执行合并…</span>
          {:else}
            <GitMerge class="h-4 w-4" />
            <span class="min-w-0 [overflow-wrap:anywhere]">
              {directoryState.selectedSources.length > 0
                ? `确认将 ${directoryState.selectedSources.length} 人合并入【${directoryState.mergeTarget.canonical_name}】`
                : "请在上方勾选要合并的联系人"}
            </span>
          {/if}
        </Button>
      </DialogFooter>
    {/if}
  </DialogContent>
</Dialog>
