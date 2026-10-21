-- RAG-Synth: chats and messages
-- Run once in the Supabase SQL editor.
-- Ownership lives on chats only; a message belongs to a user through its chat.

-- ---------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------

create table public.chats (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid()
              references auth.users (id) on delete cascade,
  title       text,
  created_at  timestamptz not null default now()
);

create table public.messages (
  -- identity id gives a reliable order: rows inserted in one statement
  -- share the same now(), so created_at alone can't order question vs answer
  id          bigint generated always as identity primary key,
  chat_id     uuid not null
              references public.chats (id) on delete cascade,
  role        text not null check (role in ('user', 'assistant')),
  content     text not null,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------

create index chats_user_id_created_at_idx on public.chats (user_id, created_at desc); -- sidebar + RLS checks
create index messages_chat_id_id_idx      on public.messages (chat_id, id);           -- chat history in order + RLS checks

-- ---------------------------------------------------------------
-- Row level security
-- ---------------------------------------------------------------

alter table public.chats    enable row level security;
alter table public.messages enable row level security;

-- chats: owner can read, create, rename and delete

create policy "Users can view their own chats"
on public.chats for select
to authenticated
using ( (select auth.uid()) = user_id );

create policy "Users can create their own chats"
on public.chats for insert
to authenticated
with check ( (select auth.uid()) = user_id );

create policy "Users can rename their own chats"
on public.chats for update
to authenticated
using ( (select auth.uid()) = user_id )        -- existing row
with check ( (select auth.uid()) = user_id );  -- resulting row

create policy "Users can delete their own chats"
on public.chats for delete
to authenticated
using ( (select auth.uid()) = user_id );

-- messages: readable and insertable only when the parent chat is the user's.
-- No update policy (messages don't change) and no delete policy:
-- deleting a chat removes its messages via the cascade, which RLS doesn't block.

create policy "Users can view messages in their own chats"
on public.messages for select
to authenticated
using (
  exists (
    select 1
    from public.chats
    where chats.id = messages.chat_id
      and chats.user_id = (select auth.uid())
  )
);

create policy "Users can add messages to their own chats"
on public.messages for insert
to authenticated
with check (
  exists (
    select 1
    from public.chats
    where chats.id = messages.chat_id
      and chats.user_id = (select auth.uid())
  )
);
