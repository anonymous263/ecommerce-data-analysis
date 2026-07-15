{#-
    hash_pii(column_expr)

    Deterministic one-way hash for PII (billing email) so plaintext never
    crosses raw -> staging. Implements the project rule:

        SHA-256( lower(trim(email)) || PII_SALT )

    - PII_SALT is injected at parse time via env_var(); it MUST be present in
      the process environment (the scratchpad dbt runner load_dotenv()s .env).
      Losing/rotating the salt breaks all customer linkage by design.
    - Uses Postgres 11+ built-in sha256(bytea); no pgcrypto extension needed.
    - Returns a lowercase hex TEXT digest, or NULL when the input is NULL/blank
      (so guest/unknown emails are handled by the caller, not hashed to a
      constant).
-#}
{% macro hash_pii(column_expr) -%}
    case
        when nullif(trim({{ column_expr }}), '') is null then null
        else encode(
            sha256(
                convert_to(
                    lower(trim({{ column_expr }})) || '{{ env_var("PII_SALT") }}',
                    'UTF8'
                )
            ),
            'hex'
        )
    end
{%- endmacro %}
