CREATE OR REPLACE VIEW public.latest_purchase_prices AS
SELECT DISTINCT ON (encode(r._fld9098rref, 'hex'))
    encode(r._fld9098rref, 'hex') AS product_id_hex,
    r._period AS price_date,
    r._fld9106 AS qty,
    ROUND(r._fld9107 / NULLIF(r._fld9106, 0), 2) AS purchase_price
FROM public._accumrg9097 r
WHERE r._active = true
  AND r._recordkind = 0
  AND encode(r._recordertref, 'hex') = '000000e6'
  AND encode(r._fld9099rref, 'hex') = '83ee60f67771497111e9dbb16ec97a48'
  AND r._fld9106 > 0
  AND r._fld9107 > 0
ORDER BY
    encode(r._fld9098rref, 'hex'),
    r._period DESC;
