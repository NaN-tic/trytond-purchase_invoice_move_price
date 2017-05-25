# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta

__all__ = ['PurchaseLine']


class PurchaseLine:
    __name__ = 'purchase.line'
    __metaclass__ = PoolMeta

    def get_invoice_line(self, invoice_type):
        lines = super(PurchaseLine, self).get_invoice_line(invoice_type)
        if self.purchase.invoice_method == 'shipment':
            for line in lines:
                if line.stock_moves:
                    line.unit_price = line.stock_moves[0].cost_price
        return lines
