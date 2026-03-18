-- Vincula a licenca ao HWID real desta maquina.
-- Projeto: https://ejwqwvscplpvvkulahac.supabase.co
-- Licenca: AUR-D8C8-2168-931A-4B5E-9692
-- HWID atual: 3f845214ffa6cd1bfbffff1b7437daf1f0cb26174133f8777291b77d18a47e12

update public.app_licenses
set
  hwids = array['3f845214ffa6cd1bfbffff1b7437daf1f0cb26174133f8777291b77d18a47e12']::text[],
  status = 'active'
where license_key = 'DCPY-AAAA-BBBB-CCCC';

select
  id,
  license_key,
  owner_name,
  status,
  hwids,
  expires_at,
  created_at
from public.app_licenses
where license_key = 'DCPY-AAAA-BBBB-CCCC';

