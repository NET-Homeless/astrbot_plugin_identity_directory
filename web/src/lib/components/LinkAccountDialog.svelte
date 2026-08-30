<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
  } from "$lib/components/ui/dialog";
  import { Link, Search, UserPlus, ArrowRight } from "lucide-svelte";
  import type { Person } from "$lib/types";

  let searchTimeout: number | null = null;
  let newPersonName = $state("");

  function handleSearch(e: Event) {
    const query = (e.target as HTMLInputElement).value;
    directoryState.linkSearchQuery = query;
    if (searchTimeout !== null) clearTimeout(searchTimeout);
    searchTimeout = window.setTimeout(() => {
      directoryState.searchLinkTargets(query);
    }, 280);
  }

  async function handleCreateAndLink() {
    if (!newPersonName.trim()) return;
    const person = await directoryState.createPerson(newPersonName.trim());
    if (person) {
      await directoryState.linkAccountToPerson(person.person_id);
    }
  }

  function handleSelectPerson(person: Person) {
    directoryState.linkAccountToPerson(person.person_id);
  }
</script>

<Dialog
  open={directoryState.isLinkOpen}
  onOpenChange={(open) => {
    directoryState.isLinkOpen = open;
    if (!open) {
      directoryState.targetAccountForLink = null;
      directoryState.linkCandidates = [];
      directoryState.linkSearchQuery = "";
      newPersonName = "";
    }
  }}
>
  <DialogContent class="max-w-md">
    <DialogHeader>
      <DialogTitle class="flex items-center gap-2 text-base font-semibold">
        <Link class="h-5 w-5 text-primary" />
        <span>绑定账号到联系人</span>
      </DialogTitle>
    </DialogHeader>

    {#if directoryState.targetAccountForLink}
      <div class="flex flex-col gap-4 py-2">
        <div class="rounded-lg border bg-muted/40 p-3 text-xs">
          <span class="text-muted-foreground">当前账号：</span>
          <code class="font-mono font-bold text-foreground">
            {directoryState.targetAccountForLink.platform}:{directoryState.targetAccountForLink.platform_user_id}
          </code>
          {#if directoryState.targetAccountForLink.username}
            <span class="text-muted-foreground">(@{directoryState.targetAccountForLink.username})</span>
          {/if}
        </div>

        <!-- Option A: Search existing person -->
        <div class="flex flex-col gap-2">
          <span class="text-xs font-semibold text-foreground">选择已有联系人：</span>
          <div class="relative">
            <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="搜索联系人规范名…"
              value={directoryState.linkSearchQuery}
              oninput={handleSearch}
              class="h-9 pl-9"
            />
          </div>

          <div class="flex flex-col gap-1.5 max-h-48 overflow-y-auto pr-1">
            {#if directoryState.linkCandidates.length === 0}
              <div class="rounded-lg border border-dashed py-6 text-center text-xs text-muted-foreground">
                {#if directoryState.linkSearchQuery.trim()}
                  未找到匹配的联系人
                {:else}
                  输入名字搜索已有联系人
                {/if}
              </div>
            {:else}
              {#each directoryState.linkCandidates as candidate (candidate.person_id)}
                <button
                  type="button"
                  onclick={() => handleSelectPerson(candidate)}
                  class="flex items-center justify-between rounded-lg border bg-card p-2.5 text-left text-xs transition-colors hover:border-primary hover:bg-muted/30"
                >
                  <span class="font-medium text-foreground">{candidate.canonical_name}</span>
                  <ArrowRight class="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              {/each}
            {/if}
          </div>
        </div>

        <!-- Option B: Create new and link -->
        <div class="flex flex-col gap-2 border-t pt-3">
          <span class="text-xs font-semibold text-foreground">或者为此账号新建联系人：</span>
          <div class="flex items-center gap-2">
            <Input
              bind:value={newPersonName}
              placeholder="输入新联系人规范名…"
              class="h-9 text-xs flex-1"
              onkeydown={(e) => {
                if (e.key === "Enter") handleCreateAndLink();
              }}
            />
            <Button size="sm" onclick={handleCreateAndLink} class="h-9 gap-1 text-xs whitespace-nowrap">
              <UserPlus class="h-3.5 w-3.5" />
              <span>创建并绑定</span>
            </Button>
          </div>
        </div>
      </div>

      <DialogFooter class="border-t pt-3">
        <Button
          variant="outline"
          size="sm"
          onclick={() => {
            directoryState.isLinkOpen = false;
          }}
        >
          取消
        </Button>
      </DialogFooter>
    {/if}
  </DialogContent>
</Dialog>
