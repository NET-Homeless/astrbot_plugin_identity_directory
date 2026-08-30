export interface Person {
  person_id: string;
  canonical_name: string;
  notes: string;
  tags: string[];
  is_bot: boolean;
  is_archived: boolean;
  created_at: number;
  updated_at: number;
}

export interface Membership {
  membership_id: string;
  account_id: string;
  group_id: string;
  current_card: string;
  first_seen: number;
  last_seen: number;
}

export interface Alias {
  alias_id: string;
  account_id: string;
  name: string;
  platform: string;
  group_id: string | null;
  source: "observed" | "manual";
  first_seen: number;
  last_seen: number;
}

export interface Account {
  account_id: string;
  platform: string;
  platform_instance_id: string;
  platform_user_id: string;
  username: string;
  person_id: string | null;
  suppress_auto_stub: boolean;
  first_seen: number;
  last_seen: number;
}

export interface AccountView extends Account {
  memberships: Membership[];
  alias_count: number;
}

export interface PersonView extends Person {
  accounts: AccountView[];
}

export interface DirectoryStats {
  persons: number;
  accounts: number;
  unlinked_accounts: number;
  memberships: number;
  aliases: number;
}

export interface PersonListResponse {
  items: Person[];
  total: number;
}

export interface AccountListResponse {
  items: AccountView[];
  total: number;
}
