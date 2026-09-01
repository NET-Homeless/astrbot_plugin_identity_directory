<script lang="ts">
  import { onMount } from "svelte";
  import { initBridge } from "$lib/bridge";
  import { directoryState } from "$lib/state.svelte";
  import Navbar from "$lib/components/Navbar.svelte";
  import PersonTable from "$lib/components/PersonTable.svelte";
  import AccountTable from "$lib/components/AccountTable.svelte";
  import PersonDetailDrawer from "$lib/components/PersonDetailDrawer.svelte";
  import MergeConfirmDialog from "$lib/components/MergeConfirmDialog.svelte";
  import LinkAccountDialog from "$lib/components/LinkAccountDialog.svelte";
  import CreatePersonDialog from "$lib/components/CreatePersonDialog.svelte";
  import { Tabs, TabsList, TabsTrigger, TabsContent } from "$lib/components/ui/tabs";
  import { Users, KeyRound, CheckCircle2, AlertCircle, Info } from "lucide-svelte";

  function applyTheme(isDark: boolean) {
    const root = document.documentElement;
    root.dataset.theme = isDark ? "dark" : "light";
    root.classList.toggle("dark", isDark);
  }

  onMount(() => {
    initBridge().then((ctx) => {
      applyTheme(Boolean(ctx.isDark));
      directoryState.refreshAll();
    });

    if (typeof window !== "undefined" && window.AstrBotPluginPage) {
      return window.AstrBotPluginPage.onContext(() => {
        const ctx = window.AstrBotPluginPage?.getContext();
        if (ctx) {
          applyTheme(Boolean(ctx.isDark));
        }
      });
    }
  });
</script>

<main class="min-h-screen bg-background text-foreground antialiased selection:bg-primary/20">
  <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 flex flex-col gap-6">
    <Navbar />

    <Tabs
      value={directoryState.activeTab}
      onValueChange={(val) => {
        directoryState.activeTab = val as "persons" | "accounts";
        directoryState.refreshAll();
      }}
      class="w-full flex flex-col gap-4"
    >
      <TabsList class="inline-flex w-auto max-w-md items-center rounded-xl bg-muted/80 p-1 border shadow-xs">
        <TabsTrigger
          value="persons"
          class="flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border"
        >
          <Users class="h-4 w-4 text-blue-500" />
          <span>联系人</span>
          {#if directoryState.stats.persons > 0}
            <span class="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-bold text-primary dark:bg-primary/20">
              {directoryState.stats.persons}
            </span>
          {/if}
        </TabsTrigger>

        <TabsTrigger
          value="accounts"
          class="flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm data-[state=active]:border"
        >
          <KeyRound class="h-4 w-4 text-emerald-500" />
          <span>平台账号</span>
          {#if directoryState.stats.accounts > 0}
            <span class="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-bold text-primary dark:bg-primary/20">
              {directoryState.stats.accounts}
            </span>
          {/if}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="persons" class="mt-0">
        <PersonTable />
      </TabsContent>

      <TabsContent value="accounts" class="mt-0">
        <AccountTable />
      </TabsContent>
    </Tabs>
  </div>

  <!-- Global Modals & Drawer -->
  <PersonDetailDrawer />
  <MergeConfirmDialog />
  <LinkAccountDialog />
  <CreatePersonDialog />

  <!-- Top-level Prominent Toast Notification Layer (Z-[9999]) -->
  {#if directoryState.toastMessage}
    <div class="fixed top-8 left-1/2 -translate-x-1/2 z-[9999] animate-in fade-in zoom-in-95 duration-200 pointer-events-none">
      <div
        class={"flex items-center gap-2.5 rounded-full px-5 py-2.5 text-xs font-bold shadow-2xl border pointer-events-auto " +
          (directoryState.toastType === "error"
            ? "bg-destructive text-destructive-foreground border-destructive"
            : directoryState.toastType === "info"
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-foreground text-background border-border")}
      >
        {#if directoryState.toastType === "error"}
          <AlertCircle class="h-4 w-4 shrink-0 text-destructive-foreground" />
        {:else if directoryState.toastType === "info"}
          <Info class="h-4 w-4 shrink-0 text-primary-foreground" />
        {:else}
          <CheckCircle2 class="h-4 w-4 shrink-0 text-emerald-400" />
        {/if}
        <span class="leading-none">{directoryState.toastMessage}</span>
      </div>
    </div>
  {/if}
</main>
