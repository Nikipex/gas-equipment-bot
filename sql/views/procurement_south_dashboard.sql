DROP VIEW IF EXISTS public.procurement_south_dashboard;

CREATE VIEW public.procurement_south_dashboard AS

WITH camino_products AS (
    SELECT
        _code AS product_code
    FROM public._reference80
    WHERE encode(_parentidrref, 'hex') = 'bdcc6a640748b82d11efde156fb54c80'
),

classified AS (
    SELECT
        p.*,

        lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) AS product_name_norm,
        regexp_replace(
            lower(replace(coalesce(p.product_name, ''), 'ё', 'е')),
            '[^a-zа-я0-9]+',
            '',
            'g'
        ) AS product_name_key,

        CASE
            WHEN EXISTS (
                SELECT 1
                FROM camino_products cp
                WHERE cp.product_code = p.product_code
            ) THEN 'коаксиалы'
            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%стальной радиатор%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%радиатор%'
                THEN 'радиаторы'

            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%baxi%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%navien%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%котел%'
                THEN 'котлы'

            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%водонагреватель%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%бойлер%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%ariston%'
                THEN 'бойлеры'

            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%колонк%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%warmix%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%genberg%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%inflame%'
                THEN 'газовые колонки'

            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%teplocom%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%solpi%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%стабилизатор%'
                THEN 'стабилизаторы'

            WHEN lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%unipump%'
              OR lower(replace(coalesce(p.product_name, ''), 'ё', 'е')) ILIKE '%насос%'
                THEN 'насосы'

            ELSE 'прочее'
        END AS product_group

    FROM public.procurement_south_mvp p
),

flags AS (
    SELECT
        c.*,

        CASE
            -- Стабилизаторы — расширенный whitelist по Solpi / Teplocom
            -- Важный ходовой Solpi-M TSD-500VA добиваем по коду товара из 1С: ОФ000006259
            WHEN product_code = 'ОФ000006259' THEN true
            WHEN product_name_norm LIKE '%solpi-m tsd-500va%' THEN true
            WHEN product_name_norm LIKE '%solpi-m%' AND product_name_norm LIKE '%tsd-500%' THEN true
            WHEN product_name_norm LIKE '%solpi%' AND product_name_norm LIKE '%tsd%' AND product_name_norm LIKE '%500%' THEN true
            WHEN product_name_key LIKE '%solpimtsd500va%' THEN true
            WHEN product_name_key LIKE '%solpimtsd500%' THEN true
            WHEN product_name_norm LIKE '%solpi%' THEN true
            WHEN product_name_key LIKE '%solpi%' THEN true
            WHEN product_name_key LIKE '%tsd500%' THEN true
            WHEN product_name_norm LIKE '%teplocom%' AND product_name_norm LIKE '%222/500%' THEN true
            WHEN product_name_norm LIKE '%teplocom%' AND product_name_norm LIKE '%555%' THEN true
            WHEN product_name_key LIKE '%teplocomst222500%' THEN true
            WHEN product_name_key LIKE '%st222500%' THEN true
            WHEN product_name_key LIKE '%teplocomst222500и%' THEN true
            WHEN product_name_key LIKE '%teplocomst555%' THEN true
            WHEN product_name_key LIKE '%st555%' THEN true
            WHEN product_name_key LIKE '%teplocomst555и%' THEN true

            -- Газовые колонки
            WHEN product_name_norm ~ 'ballu.*warmix.*gwh-10' THEN true
            WHEN product_name_norm ~ 'genberg' THEN true
            WHEN product_name_norm ~ 'inflame' THEN true

            -- Котлы — exact whitelist
            WHEN product_name_norm ~ '^котел baxi eco\s*nova\s*10f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*nova\s*14f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*nova\s*18f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*nova\s*24f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*4s\s*10\s*f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*4s\s*18\s*f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*4s\s*24$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*4s\s*24\s*f$' THEN true
            WHEN product_name_norm ~ '^котел baxi eco\s*four\s*24\s*f$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 13k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 16k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 24k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 30k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 35k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe c coaxial 40k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe one 24k\s*1 контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe one 30k\s*1 контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe e coaxial 10k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe e coaxial 13k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe e coaxial 16k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien deluxe e coaxial 24k\s*2х контур\.?$' THEN true
            WHEN product_name_norm ~ '^navien heatatmo ngb 150 24 a$' THEN true

            -- Бойлеры — нужные позиции, без Inox / FA / Superlux
            WHEN product_name_norm ~ '^водонагреватель ariston abs vls pro r 50$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston abs vls pro r 80$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston abs vls pro r 100$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston abse vls pro pw 50$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston abse vls pro pw 100$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston nts 30 v 1\.5k \(su\) slim$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston nts 50 v 1\.5k \(su\)$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston nts 80 v 1\.5k \(su\)$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston nts 100 v 1\.5k \(su\)$' THEN true
            WHEN product_name_norm ~ '^водонагреватель ariston nts fais v 1\.5k$' THEN true

            -- Насосы — whitelist по размеру модели, без привязки к UPC/CP
            WHEN product_name_norm LIKE '%unipump%'
              AND product_name_norm LIKE '%насос%'
              AND product_name_norm LIKE '%циркуляц%'
              AND (
                    (product_name_norm LIKE '%25-60%' AND product_name_norm LIKE '%180%')
                 OR (product_name_norm LIKE '%25-60%' AND product_name_norm LIKE '%130%')
                 OR (product_name_norm LIKE '%25-40%' AND product_name_norm LIKE '%180%')
                 OR (product_name_norm LIKE '%25-40%' AND product_name_norm LIKE '%130%')
                 OR (product_name_norm LIKE '%25-80%' AND product_name_norm LIKE '%180%')
                 OR (product_name_norm LIKE '%32-60%' AND product_name_norm LIKE '%180%')
                 OR (product_name_norm LIKE '%32-80%' AND product_name_norm LIKE '%180%')
              )
            THEN true

            -- Коаксиалы — всё из папки CAMINO
            WHEN product_group = 'коаксиалы' THEN true

            -- Радиаторы не тащим сюда: для них отдельная витрина radiator_procurement_mvp
            ELSE false
        END AS priority_flag,

        CASE
            -- CAMINO коаксиалы не считаем спецзаказом, иначе их режет правило "дымоход"
            WHEN product_group = 'коаксиалы' THEN false
            WHEN product_name_norm ~ 'конденсац' THEN true
            WHEN product_name_norm ~ '80/125.*конденсац' THEN true
            WHEN product_name_norm ~ 'нержав' THEN true
            WHEN product_name_norm ~ 'ремонт' THEN true
            WHEN product_name_norm ~ 'дымоход' THEN true
            WHEN product_name_norm ~ 'переходн' THEN true
            WHEN product_name_norm ~ 'форсунки' THEN true
            WHEN product_name_norm ~ 'vivat' THEN true
            WHEN product_name_norm ~ 'viessma' THEN true
            WHEN product_name_norm ~ 'ariston,?vaillant' THEN true
            WHEN product_name_norm ~ 'baxi \(кроме' THEN true
            WHEN product_name_norm ~ 'для всех моделей' THEN true
            WHEN product_name_norm ~ 'блок управления' THEN true
            WHEN product_name_norm ~ 'насосная станция' THEN true
            WHEN product_name_norm ~ 'частотн' THEN true
            WHEN product_name_norm ~ 'многоступ' THEN true
            WHEN product_name_norm ~ 'турбипресс' THEN true
            WHEN product_name_norm ~ 'тискотрон' THEN true
            ELSE false
        END AS special_order_flag

    FROM classified c
),

final AS (
    SELECT
        *,
        CASE
            WHEN product_group = 'радиаторы' THEN false
            WHEN priority_flag = true AND special_order_flag = false THEN true
            ELSE false
        END AS show_in_dashboard,

        CASE
            WHEN priority_flag = true AND stock_status IN ('critical', 'out_of_stock') THEN 1
            WHEN priority_flag = true AND stock_status = 'low' THEN 2
            WHEN priority_flag = true THEN 3
            ELSE 99
        END AS procurement_priority
    FROM flags
),

abc_ranked AS (
    SELECT
        f.*,

        GREATEST(COALESCE(f.sales_qty_60d, 0), 0) AS abc_sales_qty,

        SUM(GREATEST(COALESCE(f.sales_qty_60d, 0), 0))
            OVER (PARTITION BY f.product_group) AS abc_group_sales_qty,

        SUM(GREATEST(COALESCE(f.sales_qty_60d, 0), 0))
            OVER (
                PARTITION BY f.product_group
                ORDER BY
                    GREATEST(COALESCE(f.sales_qty_60d, 0), 0) DESC,
                    COALESCE(f.recommended_order_qty, 0) DESC,
                    f.product_name
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS abc_cumulative_sales_qty

    FROM final f
    WHERE f.show_in_dashboard = true
),

abc_classified AS (
    SELECT
        *,
        CASE
            -- Business A whitelist: these are strategic fast-moving SKUs even if the rolling window is noisy.
            WHEN product_group = 'котлы'
                 AND product_name_norm LIKE '%baxi%'
                 AND product_name_norm LIKE '%eco%'
                 AND product_name_norm LIKE '%4s%'
                 AND product_name_norm LIKE '%24%'
                THEN 'A'
            WHEN product_group = 'котлы'
                 AND product_name_norm LIKE '%baxi%'
                 AND product_name_norm LIKE '%eco%'
                 AND product_name_norm LIKE '%nova%'
                 AND product_name_norm LIKE '%24%'
                THEN 'A'
            WHEN product_group = 'котлы'
                 AND product_name_norm LIKE '%baxi%'
                 AND product_name_norm LIKE '%eco%'
                 AND product_name_norm LIKE '%four%'
                 AND product_name_norm LIKE '%24%'
                THEN 'A'
            WHEN product_group = 'котлы'
                 AND product_name_norm LIKE '%navien%'
                 AND product_name_norm LIKE '%deluxe%'
                 AND product_name_norm LIKE '%24%'
                THEN 'A'

            -- Regular ABC 60/30/10 by sales quantity inside each product group.
            -- Stabilizers intentionally use this branch too; no forced A whitelist here.
            WHEN abc_group_sales_qty <= 0 THEN 'C'
            WHEN ((abc_cumulative_sales_qty - abc_sales_qty) / NULLIF(abc_group_sales_qty, 0)) < 0.60 THEN 'A'
            WHEN ((abc_cumulative_sales_qty - abc_sales_qty) / NULLIF(abc_group_sales_qty, 0)) < 0.90 THEN 'B'
            ELSE 'C'
        END AS abc_class
    FROM abc_ranked
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY
                CASE
                    -- Unipump has duplicate rows with different casing/source spelling.
                    -- Deduplicate only Unipump pumps by normalized name.
                    WHEN product_group = 'насосы' AND product_name_norm LIKE '%unipump%'
                        THEN regexp_replace(
                            regexp_replace(product_name_norm, '\\b(upc|cp)\\b', '', 'g'),
                            '\\s+',
                            ' ',
                            'g'
                        )
                    ELSE product_group || '|' || COALESCE(product_code, '') || '|' || product_name_norm
                END
            ORDER BY
                COALESCE(sales_qty_60d, 0) DESC,
                COALESCE(avg_daily_sales, 0) DESC,
                COALESCE(recommended_order_qty, 0) DESC,
                COALESCE(stock_qty, 0) DESC,
                product_name
        ) AS dashboard_row_num
    FROM abc_classified
)

SELECT
    product_id_hex,
    product_code,
    product_name,
    product_group,
    abc_class,
    priority_flag,
    special_order_flag,
    show_in_dashboard,
    procurement_priority,
    stock_qty,
    sales_qty_60d,
    avg_daily_sales,
    days_of_cover,
    stock_status,
    recommended_order_qty,
    stock_period,
    as_of_date,
    first_sale_date,
    last_sale_date
FROM deduplicated
WHERE dashboard_row_num = 1
ORDER BY procurement_priority, abc_class, recommended_order_qty DESC, sales_qty_60d DESC;