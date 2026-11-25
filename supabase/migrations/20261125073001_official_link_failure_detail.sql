-- Keep the receipt validator and its existing permissions. Extend only the
-- rule allowlist, so both source workers can persist the same bounded detail.
do $migration$
declare
  definition text := pg_get_functiondef('machimoa_review.valid_program_failure_detail(jsonb)'::regprocedure);
  anchor constant text := 'd->>''rule'' not in (''summary_result'',';
begin
  if cardinality(string_to_array(definition, anchor)) <> 2 then
    raise exception 'Unexpected program failure rule allowlist';
  end if;
  execute replace(definition, anchor, 'd->>''rule'' not in (''official_link'',''summary_result'',');
end
$migration$;
