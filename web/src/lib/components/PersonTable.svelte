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
    Bot,
    Archive,
    ChevronLeft,
    ChevronRight,
    Pencil,
    Users,
    GitMerge,
  } from "lucide-svelte";

  let searchTimeout: number | null = null;

  function handleSearchInput(e: Event) {
    const target = e.target as HTMLInputElement;
    directoryState.personQuery = target.value;
    directoryState.personPage = 1;
    if (searchTimeout !== null) clearTimeout(searchTimeout);
    searchTimeout = window.setTimeout(() => {
      directoryState.loadPersons();
    }, 280);
  }

  function formatTime(timestamp: number): string {
    if (!timestamp) return "—";
    const d = new Date(timestamp * 1000);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  const totalPages = $derived(
    Math.max(1, Math.ceil(directoryState.personTotal / directoryState.personPageSize))
  );

  async function handleMergeClick(personId: string) {
    await directoryState.openMergeFromList(personId);
  }
</script>

<div class="flex flex-col gap-4">
  <!-- Toolbar -->
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="relative w-full max-w-sm">
      <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input
        type="search"
        placeholder="搜索规范名 / 备注画像…"
        value={directoryState.personQuery}
        oninput={handleSearchInput}
        class="h-9 pl-9"
      />
    </div>

    <div class="flex items-center gap-4">
      <label class="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
        <input
          type="checkbox"
          checked={directoryState.personArchived}
          onchange={(e) => {
            directoryState.personArchived = (e.target as HTMLInputElement).checked;
            directoryState.personPage = 1;
            directoryState.loadPersons();
          }}
          class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary dark:border-gray-700"
        />
        <span>显示已归档</span>
      </label>
    </div>
  </div>

  <!-- Data Table -->
  <div class="rounded-xl border bg-card shadow-sm overflow-hidden">
    <Table class="table-fixed w-full">
      <TableHeader>
        <TableRow class="bg-muted/40">
          <TableHead class="w-[240px]">规范名</TableHead>
          <TableHead class="w-[180px]">标签</TableHead>
          <TableHead>备注画像</TableHead>
          <TableHead class="w-[160px]">更新时间</TableHead>
          <TableHead class="w-[150px] text-right pr-4">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {#if directoryState.persons.length === 0}
          <TableRow>
            <TableCell colspan={5} class="h-32 text-center text-muted-foreground">
              <div class="flex flex-col items-center justify-center gap-2">
                <Users class="h-8 w-8 text-muted-foreground/50" />
                <p>暂无联系人记录</p>
              </div>
            </TableCell>
          </TableRow>
        {:else}
          {#each directoryState.persons as person (person.person_id)}
            <TableRow class="hover:bg-muted/30 transition-colors">
              <TableCell class="font-medium">
                <div class="flex items-center gap-1.5 min-w-0 pr-2">
                  <span
                    class="text-sm font-semibold truncate"
                    title={person.canonical_name}
                  >
                    {person.canonical_name}
                  </span>
                  {#if person.is_bot}
                    <Badge variant="secondary" class="shrink-0 gap-1 px-1.5 py-0 text-[10px] font-normal">
                      <Bot class="h-3 w-3" />
                      <span>Bot</span>
                    </Badge>
                  {/if}
                  {#if person.is_archived}
                    <Badge variant="outline" class="shrink-0 gap-1 px-1.5 py-0 text-[10px] text-muted-foreground font-normal">
                      <Archive class="h-3 w-3" />
                      <span>归档</span>
                    </Badge>
                  {/if}
                </div>
              </TableCell>

              <TableCell>
                <div class="flex flex-wrap gap-1 max-h-12 overflow-hidden">
                  {#if person.tags && person.tags.length > 0}
                    {#each person.tags as tag}
                      <Badge variant="outline" class="bg-muted/50 px-1.5 py-0 text-[11px] font-normal max-w-[120px] truncate">
                        {tag}
                      </Badge>
                    {/each}
                  {:else}
                    <span class="text-xs text-muted-foreground/60">—</span>
                  {/if}
                </div>
              </TableCell>

              <TableCell class="text-xs text-muted-foreground">
                <p class="line-clamp-2 break-all font-normal leading-relaxed">
                  {person.notes || "—"}
                </p>
              </TableCell>

              <TableCell class="text-xs text-muted-foreground whitespace-nowrap">
                {formatTime(person.updated_at)}
              </TableCell>

              <TableCell class="text-right whitespace-nowrap pr-4">
                <div class="flex items-center justify-end gap-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    onclick={() => directoryState.openPersonDetail(person.person_id)}
                    class="h-7.5 gap-1.5 px-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                    title="编辑与详情"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                    <span>编辑</span>
                  </Button>

                  <Button
                    variant="ghost"
                    size="sm"
                    onclick={() => handleMergeClick(person.person_id)}
                    class="h-7.5 gap-1.5 px-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors"
                    title="合并外部联系人进此人"
                  >
                    <GitMerge class="h-3.5 w-3.5" />
                    <span>合并</span>
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          {/each}
        {/if}
      </TableBody>
    </Table>
  </div>

  <!-- Pagination -->
  <div class="flex items-center justify-between text-xs text-muted-foreground px-1">
    <span>
      共 <strong class="font-medium text-foreground">{directoryState.personTotal}</strong> 个联系人
    </span>

    <div class="flex items-center gap-2">
      <span class="text-xs">
        第 {directoryState.personPage} / {totalPages} 页
      </span>

      <Button
        variant="outline"
        size="icon-sm"
        disabled={directoryState.personPage <= 1}
        onclick={() => {
          directoryState.personPage -= 1;
          directoryState.loadPersons();
        }}
      >
        <ChevronLeft class="h-4 w-4" />
      </Button>

      <Button
        variant="outline"
        size="icon-sm"
        disabled={directoryState.personPage >= totalPages}
        onclick={() => {
          directoryState.personPage += 1;
          directoryState.loadPersons();
        }}
      >
        <ChevronRight class="h-4 w-4" />
      </Button>
    </div>
  </div>
</div>
