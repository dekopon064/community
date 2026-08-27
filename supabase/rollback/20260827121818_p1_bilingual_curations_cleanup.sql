-- EMERGENCY DESTRUCTIVE CLEANUP ONLY.
-- Do not run without an explicit, separate approval after
-- 20260827121818_p1_bilingual_curations_down.sql has completed.
--
-- WARNING: this permanently deletes Japanese language values and the
-- split AI-status columns (ai_status_ko, ai_status_ja). Korean copies in
-- the new *_ko columns are also dropped. Old title/summary/content/ai_status
-- columns and all candidate/public rows are kept.
--
-- CASCADE is forbidden. Unexpected dependencies must fail this transaction.
-- Do not use this script to make the original forward migration runnable
-- again unless that data loss has been accepted.

begin;

do $guard$
declare
  v_enqueue_16 pg_catalog.regprocedure;
  v_enqueue_12 pg_catalog.regprocedure;
  v_missing_columns pg_catalog.text;
  v_missing_constraints pg_catalog.text;
  v_unexpected_constraints pg_catalog.text;
  v_dependent_objects pg_catalog.text;
begin
  if current_user <> 'postgres' or session_user <> 'postgres' then
    raise exception
      'P1 bilingual curations cleanup must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  v_enqueue_16 := pg_catalog.to_regprocedure(
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)'
  );
  v_enqueue_12 := pg_catalog.to_regprocedure(
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text)'
  );

  if v_enqueue_16 is not null then
    raise exception
      'run 20260827121818_p1_bilingual_curations_down.sql before cleanup; 16-argument enqueue still exists';
  end if;

  if v_enqueue_12 is null then
    raise exception
      '12-argument enqueue_curation_candidate is missing; P1 down must restore it before cleanup';
  end if;

  if pg_catalog.to_regprocedure(
       'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
     ) is null
     or pg_catalog.to_regprocedure(
       'machimoa_review.reject_curation_candidate(uuid,text,text)'
     ) is null
  then
    raise exception
      'publish or reject is missing; P1 down must restore them before cleanup';
  end if;

  select pg_catalog.string_agg(expected.col, ', ' order by expected.col)
    into v_missing_columns
  from (
    values
      ('public.curations.title_ko'),
      ('public.curations.title_ja'),
      ('public.curations.summary_ko'),
      ('public.curations.summary_ja'),
      ('public.curations.content_ko'),
      ('public.curations.content_ja'),
      ('machimoa_review.curation_candidates.title_ko'),
      ('machimoa_review.curation_candidates.title_ja'),
      ('machimoa_review.curation_candidates.summary_ko'),
      ('machimoa_review.curation_candidates.summary_ja'),
      ('machimoa_review.curation_candidates.content_ko'),
      ('machimoa_review.curation_candidates.content_ja'),
      ('machimoa_review.curation_candidates.ai_status_ko'),
      ('machimoa_review.curation_candidates.ai_status_ja')
  ) as expected(col)
  left join pg_catalog.pg_attribute as a
    on a.attrelid = pg_catalog.to_regclass(
         pg_catalog.split_part(expected.col, '.', 1)
         || '.'
         || pg_catalog.split_part(expected.col, '.', 2)
       )
   and a.attname = pg_catalog.split_part(expected.col, '.', 3)
   and a.attnum > 0
   and not a.attisdropped
  where a.attname is null;

  if v_missing_columns is not null then
    raise exception
      'P1 language columns missing before cleanup (%); refusing to continue',
      v_missing_columns;
  end if;

  select pg_catalog.string_agg(expected.con, ', ' order by expected.con)
    into v_missing_constraints
  from (
    values
      ('curations_title_ko_length_ck'),
      ('curations_title_ja_length_ck'),
      ('curations_summary_ko_length_ck'),
      ('curations_summary_ja_length_ck'),
      ('curations_content_ko_length_ck'),
      ('curations_content_ja_length_ck'),
      ('curation_candidates_title_ko_length_ck'),
      ('curation_candidates_title_ja_length_ck'),
      ('curation_candidates_summary_ko_length_ck'),
      ('curation_candidates_summary_ja_length_ck'),
      ('curation_candidates_content_ko_length_ck'),
      ('curation_candidates_content_ja_length_ck'),
      ('curation_candidates_ai_status_ko_ck'),
      ('curation_candidates_ai_status_ja_ck')
  ) as expected(con)
  left join pg_catalog.pg_constraint as c
    on c.conname = expected.con
   and c.conrelid in (
     'public.curations'::pg_catalog.regclass,
     'machimoa_review.curation_candidates'::pg_catalog.regclass
   )
  where c.conname is null;

  if v_missing_constraints is not null then
    raise exception
      'expected P1 checks missing before cleanup (%); inspect and resolve manually',
      v_missing_constraints;
  end if;

  select pg_catalog.string_agg(c.conname, ', ' order by c.conname)
    into v_unexpected_constraints
  from pg_catalog.pg_constraint as c
  where c.conrelid in (
          'public.curations'::pg_catalog.regclass,
          'machimoa_review.curation_candidates'::pg_catalog.regclass
        )
    and c.conname not in (
      'curations_title_ko_length_ck',
      'curations_title_ja_length_ck',
      'curations_summary_ko_length_ck',
      'curations_summary_ja_length_ck',
      'curations_content_ko_length_ck',
      'curations_content_ja_length_ck',
      'curation_candidates_title_ko_length_ck',
      'curation_candidates_title_ja_length_ck',
      'curation_candidates_summary_ko_length_ck',
      'curation_candidates_summary_ja_length_ck',
      'curation_candidates_content_ko_length_ck',
      'curation_candidates_content_ja_length_ck',
      'curation_candidates_ai_status_ko_ck',
      'curation_candidates_ai_status_ja_ck'
    )
    and c.contype = 'c'
    and exists (
      select 1
      from pg_catalog.unnest(c.conkey) as k(attnum)
      join pg_catalog.pg_attribute as a
        on a.attrelid = c.conrelid
       and a.attnum = k.attnum
      where a.attname in (
        'title_ko',
        'title_ja',
        'summary_ko',
        'summary_ja',
        'content_ko',
        'content_ja',
        'ai_status_ko',
        'ai_status_ja'
      )
    );

  if v_unexpected_constraints is not null then
    raise exception
      'unexpected constraints depend on P1 columns (%); resolve manually',
      v_unexpected_constraints;
  end if;

  select pg_catalog.string_agg(
           pg_catalog.pg_describe_object(d.classid, d.objid, d.objsubid),
           ', '
           order by 1
         )
    into v_dependent_objects
  from pg_catalog.pg_depend as d
  join pg_catalog.pg_attribute as a
    on a.attrelid = d.refobjid
   and a.attnum = d.refobjsubid
  where d.deptype = 'n'
    and a.attname in (
      'title_ko',
      'title_ja',
      'summary_ko',
      'summary_ja',
      'content_ko',
      'content_ja',
      'ai_status_ko',
      'ai_status_ja'
    )
    and a.attrelid in (
      'public.curations'::pg_catalog.regclass,
      'machimoa_review.curation_candidates'::pg_catalog.regclass
    )
    and not (
      d.classid = 'pg_catalog.pg_constraint'::pg_catalog.regclass
      and exists (
        select 1
        from pg_catalog.pg_constraint as con
        where con.oid = d.objid
          and con.conname in (
            'curations_title_ko_length_ck',
            'curations_title_ja_length_ck',
            'curations_summary_ko_length_ck',
            'curations_summary_ja_length_ck',
            'curations_content_ko_length_ck',
            'curations_content_ja_length_ck',
            'curation_candidates_title_ko_length_ck',
            'curation_candidates_title_ja_length_ck',
            'curation_candidates_summary_ko_length_ck',
            'curation_candidates_summary_ja_length_ck',
            'curation_candidates_content_ko_length_ck',
            'curation_candidates_content_ja_length_ck',
            'curation_candidates_ai_status_ko_ck',
            'curation_candidates_ai_status_ja_ck'
          )
      )
    );

  if v_dependent_objects is not null then
    raise exception
      'unexpected objects depend on P1 columns (%); CASCADE is forbidden',
      v_dependent_objects;
  end if;
end
$guard$;

alter table machimoa_review.curation_candidates
  drop constraint curation_candidates_title_ko_length_ck,
  drop constraint curation_candidates_title_ja_length_ck,
  drop constraint curation_candidates_summary_ko_length_ck,
  drop constraint curation_candidates_summary_ja_length_ck,
  drop constraint curation_candidates_content_ko_length_ck,
  drop constraint curation_candidates_content_ja_length_ck,
  drop constraint curation_candidates_ai_status_ko_ck,
  drop constraint curation_candidates_ai_status_ja_ck,
  drop column title_ko,
  drop column title_ja,
  drop column summary_ko,
  drop column summary_ja,
  drop column content_ko,
  drop column content_ja,
  drop column ai_status_ko,
  drop column ai_status_ja;

alter table public.curations
  drop constraint curations_title_ko_length_ck,
  drop constraint curations_title_ja_length_ck,
  drop constraint curations_summary_ko_length_ck,
  drop constraint curations_summary_ja_length_ck,
  drop constraint curations_content_ko_length_ck,
  drop constraint curations_content_ja_length_ck,
  drop column title_ko,
  drop column title_ja,
  drop column summary_ko,
  drop column summary_ja,
  drop column content_ko,
  drop column content_ja;

do $post$
declare
  v_remaining pg_catalog.text;
  v_missing_old pg_catalog.text;
begin
  select pg_catalog.string_agg(
           n.nspname || '.' || c.relname || '.' || a.attname,
           ', '
           order by n.nspname, c.relname, a.attname
         )
    into v_remaining
  from pg_catalog.pg_attribute as a
  join pg_catalog.pg_class as c
    on c.oid = a.attrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where a.attnum > 0
    and not a.attisdropped
    and a.attname in (
      'title_ko',
      'title_ja',
      'summary_ko',
      'summary_ja',
      'content_ko',
      'content_ja',
      'ai_status_ko',
      'ai_status_ja'
    )
    and (
      (n.nspname = 'public' and c.relname = 'curations')
      or (
        n.nspname = 'machimoa_review'
        and c.relname = 'curation_candidates'
      )
    );

  if v_remaining is not null then
    raise exception 'P1 columns remain after cleanup (%)', v_remaining;
  end if;

  select pg_catalog.string_agg(expected.col, ', ' order by expected.col)
    into v_missing_old
  from (
    values
      ('public.curations.title'),
      ('public.curations.summary'),
      ('public.curations.content'),
      ('machimoa_review.curation_candidates.title'),
      ('machimoa_review.curation_candidates.summary'),
      ('machimoa_review.curation_candidates.content'),
      ('machimoa_review.curation_candidates.ai_status')
  ) as expected(col)
  left join pg_catalog.pg_attribute as a
    on a.attrelid = pg_catalog.to_regclass(
         pg_catalog.split_part(expected.col, '.', 1)
         || '.'
         || pg_catalog.split_part(expected.col, '.', 2)
       )
   and a.attname = pg_catalog.split_part(expected.col, '.', 3)
   and a.attnum > 0
   and not a.attisdropped
  where a.attname is null;

  if v_missing_old is not null then
    raise exception
      'cleanup dropped unexpected legacy columns (%)',
      v_missing_old;
  end if;
end
$post$;

commit;
