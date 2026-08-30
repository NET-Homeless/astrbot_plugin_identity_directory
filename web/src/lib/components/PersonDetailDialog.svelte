<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Badge } from "$lib/components/ui/badge";
  import { Card, CardContent } from "$lib/components/ui/card";
  import { Separator } from "$lib/components/ui/separator";
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
  } from "$lib/components/ui/dialog";
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

  function handleSave() {
    if (!directoryState.activePersonId) return;
    const tagsArray = formTags
      .split(",")
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
</script>

<Dialog
  open={directoryState.isDetailOpen}
  onOpenChange={(open) => {
    directoryState.isDetailOpen = open;
    if (!open) {
      directoryState.activePersonId = null;
      directoryState.activePersonView = null;
    }
  }}
>
  <DialogContent class="max-w-2xl max-h-[88vh] overflow-y-auto">
    <DialogHeader>
      <DialogTitle class="flex items-center gap-2 text-lg">
        <User class="h-5 w-5 text-primary" />
        <span>联系人管理: {directoryState.activePersonView?.canonical_name || "—"}</span>
      </DialogTitle>
    </DialogHeader>

    {#if directoryState.activePersonView}
      <div class="flex flex-col gap-6 py-2">
        <!-- Core Profile Form -->
        <div class="grid gap-4">
          <div class="grid gap-1.5">
            <label for="f-canonical" class="text-xs font-semibold text-muted-foreground">规范名（全局唯一主昵称）</label>
            <Input id="f-canonical" bind:value={formName} placeholder="如：联系人甲、联系人乙" class="h-9 font-medium" />
          </div>

          <div class="grid gap-1.5">
            <label for="f-tags" class="text-xs font-semibold text-muted-foreground">标签（英文/中文逗号分隔）</label>
            <Input id="f-tags" bind:value={formTags} placeholder="如：主人, 开发者, 管理员" class="h-9" />
          </div>

          <div class="grid gap-1.5">
            <label for="f-notes" class="text-xs font-semibold text-muted-foreground">画像备注 / 用户信息</label>
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
                class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <span>设定为 Bot / 虚拟角色</span>
            </label>

            <label class="flex items-center gap-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                bind:checked={formIsArchived}
                class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <span>归档该联系人</span>
            </label>
          </div>
        </div>

        <Separator />

        <!-- Linked Accounts -->
        <div class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h3 class="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <KeyRound class="h-4 w-4 text-emerald-500" />
              <span>绑定的平台账号 ({directoryState.activePersonView.accounts.length})</span>
            </h3>
          </div>

          {#if directoryState.activePersonView.accounts.length === 0}
            <div class="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
              未绑定任何平台账号，可在账号列表中进行关联绑定
            </div>
          {:else}
            <div class="grid gap-2">
              {#each directoryState.activePersonView.accounts as account (account.account_id)}
                <Card class="bg-muted/30 border-muted">
                  <CardContent class="p-3">
                    <div class="flex items-center justify-between gap-2">
                      <div class="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" class="font-mono text-xs">
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

                    <!-- Memberships / Group Cards in this account -->
                    {#if account.memberships && account.memberships.length > 0}
                      <div class="mt-2 flex flex-wrap gap-1.5">
                        {#each account.memberships as m}
                          <span class="inline-flex items-center gap-1 rounded bg-background/80 px-2 py-0.5 text-[11px] border">
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

        <!-- Aliases History -->
        <div class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h3 class="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <Tags class="h-4 w-4 text-purple-500" />
              <span>别名与显示名历史 ({directoryState.activePersonAliases.length})</span>
            </h3>
          </div>

          <div class="flex flex-wrap gap-1.5">
            {#if directoryState.activePersonAliases.length === 0}
              <span class="text-xs text-muted-foreground/60">暂无别名历史</span>
            {:else}
              {#each directoryState.activePersonAliases as alias (alias.alias_id)}
                <Badge variant="secondary" class="gap-1.5 py-1 px-2.5 text-xs font-normal">
                  <span>{alias.name}</span>
                  <span class="text-[10px] text-muted-foreground">
                    ({alias.group_id ? `群 ${alias.group_id}` : alias.platform})
                  </span>
                  <button
                    type="button"
                    onclick={() => directoryState.deleteAlias(alias.alias_id)}
                    class="ml-0.5 text-muted-foreground hover:text-destructive"
                  >
                    <X class="h-3 w-3" />
                  </button>
                </Badge>
              {/each}
            {/if}
          </div>

          <!-- Add Alias Form -->
          {#if directoryState.activePersonView.accounts.length > 0}
            <div class="mt-2 flex items-center gap-2">
              <Input
                bind:value={newAliasName}
                placeholder="手动新增曾用名 / 别名…"
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
      </div>

      <DialogFooter class="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
        <div class="flex items-center gap-2">
          <Button
            variant="destructive"
            size="sm"
            onclick={handleDelete}
            class="h-9 gap-1.5"
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
            class="h-9 gap-1.5"
          >
            <GitMerge class="h-4 w-4 text-purple-500" />
            <span>合并到另一联系人…</span>
          </Button>
        </div>

        <Button size="sm" onclick={handleSave} class="h-9 gap-1.5">
          <Save class="h-4 w-4" />
          <span>保存修改</span>
        </Button>
      </DialogFooter>
    {/if}
  </DialogContent>
</Dialog>
