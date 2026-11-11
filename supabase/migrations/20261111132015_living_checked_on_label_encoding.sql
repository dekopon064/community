-- Repair date-label literals damaged during SQL text transport.
-- ASCII-only SQL avoids dependence on the deployment shell's text encoding.
-- Publication content before the generated footer and all images stay identical.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $repair$
declare
  target regprocedure := 'public.admin_living_write(uuid,text,uuid,text,jsonb,uuid)'::regprocedure;
  definition text;
  rewritten text;
  old_ko text := U&'\fffd\fffd\fffd\fffd \022e\fffd\fffd\fffd\fffd: ';
  old_ja text := U&'\fffd\fffd\fffd\fffd\fffd\fffd\fffd\fffd\fffd\fffd: ';
  good_ko text := U&'\c815\bcf4 \d655\c778\c77c: ';
  good_ja text := U&'\60c5\5831\78ba\8a8d\65e5: ';
  old_ko_expr text;
  old_ja_expr text;
  new_ko_expr text;
  new_ja_expr text;
  canonical_ko_expr text;
  canonical_ja_expr text;
  function_before jsonb;
  documents_before text;
  assets_before text;
  other_rows_before text;
  row_before jsonb;
  row_after jsonb;
  r record;
  ko_suffix text;
  ja_suffix text;
  fixed_ko text;
  fixed_ja text;
  fixed_legacy text;
  ko_body text;
  ja_body text;
  count_fixed integer := 0;
begin
  select jsonb_build_object('oid',oid,'owner',proowner,'acl',proacl::text,
    'config',proconfig,'definer',prosecdef)
    into function_before from pg_proc where oid=target;

  select pg_get_functiondef(target) into definition;
  -- E-string syntax is kept exact while only its label is replaced.
  old_ko_expr := 'ko:=ko||E' || chr(39) || chr(92)||'n'||chr(92)||'n'||old_ko||chr(39);
  old_ja_expr := 'ja:=ja||E' || chr(39) || chr(92)||'n'||chr(92)||'n'||old_ja||chr(39);
  new_ko_expr := 'ko:=ko||E' || chr(39)||chr(92)||'n'||chr(92)||'n'||chr(39) || '||U&' || chr(39) || chr(92)||'c815'||chr(92)||'bcf4 '||chr(92)||'d655'||chr(92)||'c778'||chr(92)||'c77c: '||chr(39);
  new_ja_expr := 'ja:=ja||E' || chr(39)||chr(92)||'n'||chr(92)||'n'||chr(39) || '||U&' || chr(39) || chr(92)||'60c5'||chr(92)||'5831'||chr(92)||'78ba'||chr(92)||'8a8d'||chr(92)||'65e5: '||chr(39);
  canonical_ko_expr := 'ko:=ko||E' || chr(39)||chr(92)||'n'||chr(92)||'n'||good_ko||chr(39);
  canonical_ja_expr := 'ja:=ja||E' || chr(39)||chr(92)||'n'||chr(92)||'n'||good_ja||chr(39);
  -- Canonical UTF-8 installs and already repaired installs are valid too.
  -- Unknown implementations still fail closed instead of replacing their bodies.
  if (strpos(definition,old_ko_expr)=0 and strpos(definition,canonical_ko_expr)=0 and strpos(definition,new_ko_expr)=0)
    or (strpos(definition,old_ja_expr)=0 and strpos(definition,canonical_ja_expr)=0 and strpos(definition,new_ja_expr)=0) then
    raise exception 'living date label predecessor differs';
  end if;
  rewritten := replace(replace(replace(replace(definition,old_ko_expr,new_ko_expr),old_ja_expr,new_ja_expr),canonical_ko_expr,new_ko_expr),canonical_ja_expr,new_ja_expr);
  if rewritten is distinct from definition then execute rewritten; end if;
  if (select jsonb_build_object('oid',oid,'owner',proowner,'acl',proacl::text,
    'config',proconfig,'definer',prosecdef) from pg_proc where oid=target)
    is distinct from function_before then
    raise exception 'living write privileges changed';
  end if;

  select md5(coalesce(string_agg(to_jsonb(d)::text,'' order by id),'')) into documents_before
    from machimoa_review.living_articles d;
  select md5(coalesce(string_agg(to_jsonb(a)::text,'' order by id),'')) into assets_before
    from machimoa_review.living_image_assets a;
  select md5(coalesce(string_agg(to_jsonb(c)::text,'' order by id),'')) into other_rows_before
    from public.curations c where not exists
      (select 1 from machimoa_review.living_articles d where d.published_id=c.id
        and d.status='published' and coalesce(d.document->>'checkedOn','')<>'');

  for r in select c.id,d.document,d.id article_id
    from machimoa_review.living_articles d join public.curations c on c.id=d.published_id
    where d.status='published' and coalesce(d.document->>'checkedOn','')<>''
      and c.source='machimoa_living' and c.source_item_id=d.id::text
    order by c.id for update of c
  loop
    select to_jsonb(c) into row_before from public.curations c where c.id=r.id;
    ko_suffix := E'\n\n'||old_ko||(r.document->>'checkedOn');
    ja_suffix := E'\n\n'||old_ja||(r.document->>'checkedOn');
    ko_body := row_before->>'content_ko';
    ja_body := row_before->>'content_ja';
    if right(ko_body,length(ko_suffix))=ko_suffix
      and right(ja_body,length(ja_suffix))=ja_suffix then
      fixed_ko := left(ko_body,length(ko_body)-length(ko_suffix))||E'\n\n'||good_ko||(r.document->>'checkedOn');
      fixed_ja := left(ja_body,length(ja_body)-length(ja_suffix))||E'\n\n'||good_ja||(r.document->>'checkedOn');
      fixed_legacy := row_before->>'content';
      if fixed_legacy=ko_body then fixed_legacy:=fixed_ko;
      elsif right(fixed_legacy,length(ko_suffix))=ko_suffix then
        fixed_legacy:=left(fixed_legacy,length(fixed_legacy)-length(ko_suffix))||E'\n\n'||good_ko||(r.document->>'checkedOn');
      end if;
      update public.curations set content_ko=fixed_ko,content_ja=fixed_ja,content=fixed_legacy where id=r.id;
      select to_jsonb(c) into row_after from public.curations c where c.id=r.id;
      if (row_before - array['content','content_ko','content_ja'])
        is distinct from (row_after - array['content','content_ko','content_ja']) then
        raise exception 'non-footer publication metadata changed';
      end if;
      count_fixed:=count_fixed+1;
    elsif right(ko_body,length(E'\n\n'||good_ko||(r.document->>'checkedOn')))=E'\n\n'||good_ko||(r.document->>'checkedOn')
      and right(ja_body,length(E'\n\n'||good_ja||(r.document->>'checkedOn')))=E'\n\n'||good_ja||(r.document->>'checkedOn') then
      null;
    else raise exception 'living date footer differs for %',r.article_id;
    end if;
  end loop;

  if (select md5(coalesce(string_agg(to_jsonb(d)::text,'' order by id),'')) from machimoa_review.living_articles d) is distinct from documents_before
    or (select md5(coalesce(string_agg(to_jsonb(a)::text,'' order by id),'')) from machimoa_review.living_image_assets a) is distinct from assets_before
    or (select md5(coalesce(string_agg(to_jsonb(c)::text,'' order by id),'')) from public.curations c where not exists
      (select 1 from machimoa_review.living_articles d where d.published_id=c.id and d.status='published' and coalesce(d.document->>'checkedOn','')<>'')) is distinct from other_rows_before then
    raise exception 'living document, image or unrelated publication changed';
  end if;
  raise notice 'Repaired generated date labels on % living publications',count_fixed;
end
$repair$;
commit;
