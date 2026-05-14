# -*- coding: utf-8 -*-
from .kasa_core import KasaCoreMixin
from .kasa_users import KasaUserMixin
from .kasa_customers import KasaCustomerMixin
from .kasa_products import KasaProductSaleMixin
from .kasa_reports import KasaReportMixin


class KasaDatabase(
    KasaCoreMixin,
    KasaUserMixin,
    KasaCustomerMixin,
    KasaProductSaleMixin,
    KasaReportMixin,
):
    """Main kasa database facade composed from focused data-access mixins."""

    pass
