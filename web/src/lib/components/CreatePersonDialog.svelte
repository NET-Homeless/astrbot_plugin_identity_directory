<script lang="ts">
  import { directoryState } from "$lib/state.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
  } from "$lib/components/ui/dialog";
  import { UserPlus } from "lucide-svelte";

  let name = $state("");
  let tags = $state("");
  let notes = $state("");

  async function handleCreate() {
    if (!name.trim()) return;
    const tagArray = tags
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    const created = await directoryState.createPerson(name.trim(), notes, tagArray);
    if (created) {
      name = "";
      tags = "";
      notes = "";
    }
  }
</script>

<Dialog
  open={directoryState.isCreatePersonOpen}
  onOpenChange={(open) => {
    directoryState.isCreatePersonOpen = open;
    if (!open) {
      name = "";
      tags = "";
      notes = "";
    }
  }}
>
  <DialogContent class="max-w-md">
    <DialogHeader>
      <DialogTitle class="flex items-center gap-2 text-base font-semibold">
        <UserPlus class="h-5 w-5 text-primary" />
        <span>新建联系人</span>
      </DialogTitle>
    </DialogHeader>

    <div class="flex flex-col gap-4 py-2">
      <div class="grid gap-1.5">
        <label for="c-name" class="text-xs font-semibold text-muted-foreground">规范名（必填）</label>
        <Input id="c-name" bind:value={name} placeholder="如：联系人甲、联系人乙" class="h-9 font-medium" />
      </div>

      <div class="grid gap-1.5">
        <label for="c-tags" class="text-xs font-semibold text-muted-foreground">标签（可选，逗号分隔）</label>
        <Input id="c-tags" bind:value={tags} placeholder="如：主人, 开发者, 管理员" class="h-9" />
      </div>

      <div class="grid gap-1.5">
        <label for="c-notes" class="text-xs font-semibold text-muted-foreground">画像备注 / 用户信息</label>
        <Textarea
          id="c-notes"
          bind:value={notes}
          rows={3}
          placeholder="记录该用户的喜好、职业、特征与背景等画像信息…"
          class="text-xs leading-relaxed resize-y"
        />
      </div>
    </div>

    <DialogFooter class="border-t pt-3">
      <Button
        variant="outline"
        size="sm"
        onclick={() => {
          directoryState.isCreatePersonOpen = false;
        }}
      >
        取消
      </Button>

      <Button size="sm" onclick={handleCreate} disabled={!name.trim()} class="gap-1.5">
        <UserPlus class="h-4 w-4" />
        <span>立即创建</span>
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
