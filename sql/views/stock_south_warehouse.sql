CREATE OR REPLACE VIEW public.stock_south_warehouse AS
WITH latest_period AS (
    SELECT MAX(s._period) AS max_period
    FROM public._accumrgt9117 s
    WHERE s._fld9099rref = decode('83ee60f67771497111e9dbb16ec97a48','hex')
)
SELECT
    s._period AS stock_period,
    n._code AS product_code,
    n._description AS product_name,
    s._fld9106 AS stock_qty,
    s._fld9107 AS stock_amount
FROM public._accumrgt9117 s
JOIN public._reference80 n
    ON s._fld9098rref = n._idrref
WHERE s._fld9099rref = decode('83ee60f67771497111e9dbb16ec97a48','hex')
  AND s._period = (SELECT max_period FROM latest_period)
  AND s._fld9106 <> 0;