from __future__ import annotations

from .job import business_for_sku
from .price import normalize_price_value


class TemplateSubmitReadyError(RuntimeError):
    pass


def listing_prices(child, business, *, submit_ready):
    """The seller owns the offer. A source list price is usable only in its authorized role."""
    price = normalize_price_value(business.get('list_price'), allow_zero=True)
    policy = business.get('price_policy')
    offer = child.get('offer') or {}
    own = offer.get('owner_asin') == child.get('asin')
    if not price and (not submit_ready or policy in {'use_source_list_price', 'same_as_list_price'}):
        if (offer.get('price_field') == 'listPrice' and offer.get('owner_asin') == child.get('asin')
                and str(offer.get('currency') or '').upper() in {'$', 'USD', 'US$'}):
            price = normalize_price_value(offer.get('list_price'))
    if not price and business.get('marketplace', 'US') == 'US':
        price = '0.00'  # The US template explicitly accepts zero for no reference price.
    selling = normalize_price_value(business.get('selling_price'))
    if policy == 'same_as_list_price':
        selling = normalize_price_value(price) or selling
        if not selling and own and str(offer.get('current_currency') or '').upper() in {'$', 'USD', 'US$'}:
            selling = normalize_price_value(offer.get('current_price'))
    return {'list_price':price, 'selling_price':selling}


def assert_submit_ready_price_current(listing_rows, source_children, *, mode, job):
    if mode != 'submit_ready':
        return
    sources = {child['asin']:child for child in source_children}
    for row in listing_rows:
        if row.get('row_type') != 'Child':
            continue
        business = business_for_sku(job, row['sku'], submit_ready=True)
        expected = listing_prices(sources[row['asin']], business, submit_ready=True)
        for field, price in expected.items():
            actual = (row.get('offer') or {}).get(field)
            if (price or actual not in (None,'')) and (not price or price != normalize_price_value(actual, allow_zero=field=='list_price')):
                raise TemplateSubmitReadyError(f"{row['sku']} {field} differs from its authorized value: expected {price!r}, got {actual!r}")
