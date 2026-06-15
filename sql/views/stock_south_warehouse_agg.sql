CREATE OR REPLACE VIEW public.stock_south_warehouse_agg AS
WITH current_stock AS (
    -- В 1С итоговые таблицы остатков используют технический период 3999-11-01
    -- как актуальный срез состояния регистра.
    -- Поэтому для текущего свободного остатка берём именно этот период,
    -- а не MAX(stock_period) по календарным датам.
    SELECT
        product_code,
        product_name,
        stock_qty,
        stock_amount,
        stock_period
    FROM public.stock_south_warehouse
    WHERE stock_period = TIMESTAMP '3999-11-01 00:00:00'
      AND stock_qty <> 0
),
base AS (
    SELECT
        product_code,
        product_name,
        stock_qty,
        stock_amount,
        stock_period,

        -- Мягкая нормализация: чистим пробелы и регистр,
        -- но НЕ удаляем (1,2), RUTERM, VK, universal и другие варианты исполнения,
        -- потому что это разные реальные позиции в отчёте 1С.
        TRIM(
            REGEXP_REPLACE(
                LOWER(product_name),
                '\s+',
                ' ',
                'g'
            )
        ) AS normalized_name
    FROM current_stock
)
SELECT
    MIN(product_code) AS product_code,
    normalized_name AS product_name,
    SUM(stock_qty) AS stock_qty,
    SUM(stock_amount) AS stock_amount,
    MAX(stock_period) AS stock_period,
    (SELECT MAX(sale_period)::date FROM public.sales_south_warehouse) AS as_of_date
FROM base
GROUP BY normalized_name
HAVING SUM(stock_qty) <> 0;