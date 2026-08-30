<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Badge } from "$lib/components/ui/badge";
  import { Card, CardContent } from "$lib/components/ui/card";
  import { Separator } from "$lib/components/ui/separator";
  import {
    User,
    Save,
    Trash2,
    GitMerge,
    Unlink,
    Plus,
    X,
    MessageSquare,
    KeyRound,
    Loader2,
    Tags,
  } from "lucide-svelte";

  let formName = $state("");
  let formTags = $state("");
  let formNotes = $state("");
  let formIsBot = $state(false);
  let formIsArchived = $state(false);

  // New alias form
  let newAliasName = $state("");
  let newAliasAccountId = $state("");

  $effect(() => {
    if (directoryState.activePersonView) {
      const p = directoryState.activePersonView;
      formName = p.canonical_name;
      formTags = (p.tags || []).join(", ");
      formNotes = p.notes || "";
      formIsBot = p.is_bot;
      formIsArchived = p.is_archived;

      if (p.accounts.length > 0 && !newAliasAccountId) {
        newAliasAccountId = p.accounts[0].account_id;
      }
    }
  });

  function closeDrawer() {
    directoryState.isDetailOpen = false;
    directoryState.activePersonId = null;
    directoryState.activePersonView = null;
  }

  function handleSave() {
    if (!directoryState.activePersonId) return;
    const tagsArray = formTags
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    directoryState.savePerson(directoryState.activePersonId, {
      canonical_name: formName.trim(),
      tags: tagsArray,
      notes: formNotes,
      is_bot: formIsBot,
      is_archived: formIsArchived,
    });
  }

  function handleDelete() {
    if (!directoryState.activePersonId || !directoryState.activePersonView) return;
    if (
      window.confirm(
        `确定删除联系人【${directoryState.activePersonView.canonical_name}】？其关联账号将变为未绑定状态。`
      )
    ) {
      directoryState.deletePerson(directoryState.activePersonId);
    }
  }

  function handleAddAlias() {
    if (!newAliasName.trim() || !newAliasAccountId || !directoryState.activePersonView) return;
    const account = directoryState.activePersonView.accounts.find(
      (a) => a.account_id === newAliasAccountId
    );
    if (!account) return;
    directoryState.addAlias(newAliasAccountId, newAliasName.trim(), account.platform);
    newAliasName = "";
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && directoryState.isDetailOpen) {
      closeDrawer();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if directoryState.isDetailOpen}
  <!-- Backdrop -->
  <div
    role="presentation"
    onclick={closeDrawer}
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-xs transition-opacity duration-200"
  ></div>

  <!-- Right Drawer Panel -->
  <aside
    class="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col bg-card text-card-foreground shadow-2xl border-l duration-300 ease-in-out sm:max-w-xl"
    aria-label="联系人管理抽屉"
  >
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-6 py-4 bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <User class="h-4 w-4" />
        </div>
        <div>
          <h2 class="text-base font-bold text-foreground">
            {directoryState.activePersonView?.canonical_name || "联系人详情"}
          </h2>
          <p class="text-[11px] text-muted-foreground">编辑规范身份、管理绑定账号与别名历史</p>
        </div>
      </div>

      <Button
        variant="ghost"
        size="icon-sm"
        onclick={closeDrawer}
        class="h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground"
      >
        <X class="h-4 w-4" />
      </Button>
    </div>

    <!-- Scrollable Content -->
    <div class="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-6">
      {#if directoryState.activePersonView}
        <!-- Profile Form -->
        <div class="flex flex-col gap-4">
          <div class="grid gap-1.5">
            <label for="f-canonical" class="text-xs font-semibold text-foreground">
              规范名（全局唯一主昵称）
            </label>
            <Input id="f-canonical" bind:value={formName} placeholder="如：starshine、联系人乙" class="h-9 font-medium" />
          </div>

          <div class="grid gap-1.5">
            <label for="f-tags" class="text-xs font-semibold text-foreground">
              标签（英文/中文逗号分隔）
            </label>
            <Input id="f-tags" bind:value={formTags} placeholder="如：主人, 开发者, 管理员" class="h-9" />
          </div>

          <div class="grid gap-1.5">
            <label for="f-notes" class="text-xs font-semibold text-foreground">
              画像备注 / 用户背景信息
            </label>
            <Textarea
              id="f-notes"
              bind:value={formNotes}
              rows={3}
              placeholder="记录该用户的喜好、职业、特征与背景等画像信息…"
              class="text-xs leading-relaxed resize-y"
            />
          </div>

          <div class="flex items-center gap-6 pt-1">
            <label class="flex items-center gap-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                bind:checked={formIsBot}
                class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary dark:border-gray-700"
              />
              <span>设定为 Bot / 虚拟角色</span>
            </label>

            <label class="flex items-center gap-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                bind:checked={formIsArchived}
                class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary dark:border-gray-700"
              />
              <span>归档该联系人</span>
            </label>
          </div>
        </div>

        <Separator />

        <!-- Linked Accounts Section -->
        <div class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h3 class="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
              <KeyRound class="h-3.5 w-3.5 text-emerald-500" />
              <span>绑定的平台账号 ({directoryState.activePersonView.accounts.length})</span>
            </h3>
          </div>

          {#if directoryState.activePersonView.accounts.length === 0}
            <div class="rounded-xl border border-dashed p-5 text-center text-xs text-muted-foreground">
              未绑定任何平台账号，可在账号列表中点击“绑定”进行关联
            </div>
          {:else}
            <div class="grid gap-2.5">
              {#each directoryState.activePersonView.accounts as account (account.account_id)}
                <Card class="bg-muted/40 border-border/80 shadow-none">
                  <CardContent class="p-3.5">
                    <div class="flex items-center justify-between gap-2">
                      <div class="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" class="font-mono text-xs px-2 py-0.5">
                          {account.platform}
                        </Badge>
                        <code class="font-mono text-xs font-bold text-foreground">
                          {account.platform_user_id}
                        </code>
                        {#if account.username}
                          <span class="text-xs text-muted-foreground">(@{account.username})</span>
                        {/if}
                      </div>

                      <Button
                        variant="ghost"
                        size="sm"
                        onclick={() => directoryState.unlinkAccount(account.account_id)}
                        class="h-7 px-2 text-xs text-destructive hover:bg-destructive/10"
                      >
                        <Unlink class="mr-1 h-3 w-3" />
                        <span>解绑</span>
                      </Button>
                    </div>

                    <!-- Memberships / Group Cards -->
                    {#if account.memberships && account.memberships.length > 0}
                      <div class="mt-2.5 flex flex-wrap gap-1.5 pt-2 border-t border-border/50">
                        {#each account.memberships as m}
                          <span class="inline-flex items-center gap-1 rounded-md bg-background px-2 py-0.5 text-[11px] border text-foreground">
                            <MessageSquare class="h-3 w-3 text-muted-foreground" />
                            <strong>{m.current_card || "（无群名片）"}</strong>
                            <span class="text-[10px] text-muted-foreground">@{m.group_id}</span>
                          </span>
                        {/each}
                      </div>
                    {/if}
                  </CardContent>
                </Card>
              {/each}
            </div>
          {/if}
        </div>

        <Separator />

        <!-- Aliases History Section -->
        <div class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h3 class="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
              <Tags class="h-3.5 w-3.5 text-purple-500" />
              <span>显示名与别名历史 ({directoryState.activePersonAliases.length})</span>
            </h3>
          </div>

          <div class="flex flex-wrap gap-1.5">
            {#if directoryState.activePersonAliases.length === 0}
              <span class="text-xs text-muted-foreground/60">暂无历史别名记录</span>
            {:else}
              {#each directoryState.activePersonAliases as alias (alias.alias_id)}
                <Badge variant="secondary" class="gap-1.5 py-1 px-2.5 text-xs font-normal">
                  <span class="font-medium text-foreground">{alias.name}</span>
                  <span class="text-[10px] text-muted-foreground">
                    ({alias.group_id ? `群 ${alias.group_id}` : alias.platform})
                  </span>
                  <button
                    type="button"
                    onclick={() => directoryState.deleteAlias(alias.alias_id)}
                    class="ml-0.5 text-muted-foreground hover:text-destructive"
                    title="删除别名"
                  >
                    <X class="h-3 w-3" />
                  </button>
                </Badge>
              {/each}
            {/if}
          </div>

          <!-- Add Alias Form -->
          {#if directoryState.activePersonView.accounts.length > 0}
            <div class="mt-1.5 flex items-center gap-2">
              <Input
                bind:value={newAliasName}
                placeholder="手动新增别名…"
                class="h-8 text-xs flex-1"
                onkeydown={(e) => {
                  if (e.key === "Enter") handleAddAlias();
                }}
              />

              <select
                bind:value={newAliasAccountId}
                class="h-8 rounded-md border bg-background px-2 text-xs text-foreground focus:ring-1 focus:ring-primary"
              >
                {#each directoryState.activePersonView.accounts as account}
                  <option value={account.account_id}>
                    {account.platform}:{account.platform_user_id}
                  </option>
                {/each}
              </select>

              <Button size="sm" variant="outline" onclick={handleAddAlias} class="h-8 gap-1 px-2.5 text-xs">
                <Plus class="h-3.5 w-3.5" />
                <span>添加</span>
              </Button>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Fixed Bottom Action Bar -->
    <div class="flex flex-wrap items-center justify-between gap-3 border-t bg-card px-6 py-4">
      <div class="flex items-center gap-2">
        <Button
          variant="destructive"
          size="sm"
          onclick={handleDelete}
          class="h-9 gap-1.5 text-xs"
        >
          <Trash2 class="h-4 w-4" />
          <span>删除联系人</span>
        </Button>

        <Button
          variant="outline"
          size="sm"
          onclick={() => {
            if (directoryState.activePersonView) {
              directoryState.openMerge(directoryState.activePersonView);
            }
          }}
          class="h-9 gap-1.5 text-xs"
        >
          <GitMerge class="h-4 w-4 text-purple-500" />
          <span>合并联系人…</span>
        </Button>
      </div>

      <Button size="sm" onclick={handleSave} disabled={directoryState.isSaving} class="h-9 gap-1.5 text-xs">
        {#if directoryState.isSaving}
          <Loader2 class="h-4 w-4 animate-spin" />
          <span>正在保存…</span>
        {:else}
          <Save class="h-4 w-4" />
          <span>保存修改</span>
        {/if}
      </Button>
    </div>
  </aside>
{/if}
