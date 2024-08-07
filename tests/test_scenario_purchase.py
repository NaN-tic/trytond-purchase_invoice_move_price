import datetime
import unittest
from decimal import Decimal

from proteus import Model
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        today = datetime.date.today()

        # Activate purchase_invoice_move_price
        config = activate_modules('purchase_invoice_move_price')

        # Create company
        _ = create_company()
        company = get_company()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create parties
        Party = Model.get('party.party')
        supplier = Party(name='Supplier')
        supplier.save()

        # Create account category
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.customer_taxes.append(tax)
        account_category.save()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        ProductTemplate = Model.get('product.template')
        Product = Model.get('product.product')
        product = Product()
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'goods'
        template.purchasable = True
        template.list_price = Decimal('10')
        template.cost_price_method = 'fixed'
        template.account_category = account_category
        template.save()
        product.template = template
        product.cost_price = Decimal('5')
        product.save()

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create an Inventory
        Inventory = Model.get('stock.inventory')
        InventoryLine = Model.get('stock.inventory.line')
        Location = Model.get('stock.location')
        storage, = Location.find([
            ('code', '=', 'STO'),
        ])
        inventory = Inventory()
        inventory.location = storage
        inventory.save()
        inventory_line = InventoryLine(product=product, inventory=inventory)
        inventory_line.quantity = 100.0
        inventory_line.expected_quantity = 0.0
        inventory.save()
        inventory_line.save()
        Inventory.confirm([inventory.id], config.context)
        self.assertEqual(inventory.state, 'done')

        # Purchase 5 products
        Purchase = Model.get('purchase.purchase')
        PurchaseLine = Model.get('purchase.line')
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase.invoice_method = 'order'
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.product = product
        purchase_line.quantity = 2.0
        purchase_line.unit_price = product.cost_price
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.type = 'comment'
        purchase_line.description = 'Comment'
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.product = product
        purchase_line.quantity = 3.0
        purchase_line.unit_price = product.cost_price
        purchase.click('quote')
        purchase.click('confirm')
        purchase.click('process')
        invoice, = purchase.invoices
        self.assertEqual(invoice.origins, purchase.rec_name)

        # Invoice line must be linked to stock move
        invoice_line1, invoice_line2 = sorted(invoice.lines,
                                              key=lambda l: l.quantity or 0)
        self.assertEqual(invoice_line1.unit_price, Decimal('5.0000'))
        self.assertEqual(invoice_line2.unit_price, Decimal('5.0000'))

        # Purchase 5 products with an invoice method 'on shipment'
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase.invoice_method = 'shipment'
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.product = product
        purchase_line.quantity = 2.0
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.type = 'comment'
        purchase_line.description = 'Comment'
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.product = product
        purchase_line.quantity = 3.0
        purchase.click('quote')
        purchase.click('confirm')
        purchase.click('process')
        self.assertEqual(len(purchase.moves), 2)

        self.assertEqual(len(purchase.shipment_returns), 0)

        self.assertEqual(len(purchase.invoices), 0)

        # Not yet linked to invoice lines
        stock_move1, stock_move2 = sorted(purchase.moves,
                                          key=lambda m: m.quantity)
        self.assertEqual(len(stock_move1.invoice_lines), 0)
        self.assertEqual(len(stock_move2.invoice_lines), 0)

        # Validate Shipments giving a different unit price
        Move = Model.get('stock.move')
        ShipmentIn = Model.get('stock.shipment.in')
        shipment = ShipmentIn()
        shipment.supplier = supplier

        for move in purchase.moves:
            incoming_move = Move(id=move.id)
            incoming_move.unit_price = Decimal('20')
            shipment.incoming_moves.append(incoming_move)

        shipment.save()
        self.assertEqual(shipment.origins, purchase.rec_name)
        ShipmentIn.receive([shipment.id], config.context)
        ShipmentIn.do([shipment.id], config.context)
        purchase.reload()
        self.assertEqual(len(purchase.shipments), 1)

        self.assertEqual(len(purchase.shipment_returns), 0)

        # Open supplier invoice
        Invoice = Model.get('account.invoice')
        invoice, = purchase.invoices
        self.assertEqual(invoice.type, 'in')
        invoice_line1, invoice_line2 = sorted(invoice.lines,
                                              key=lambda l: l.quantity)

        for line in invoice.lines:
            line.quantity = 1
            line.save()

        invoice.invoice_date = today
        invoice.save()
        Invoice.post([invoice.id], config.context)

        # Invoice lines must be linked to each stock moves
        self.assertEqual(invoice_line1.stock_moves, [stock_move1])
        self.assertEqual(invoice_line2.stock_moves, [stock_move2])

        # Invoice lines must have the same price as the one given in the shipment
        self.assertEqual(invoice_line1.unit_price, Decimal('20.0000'))
        self.assertEqual(invoice_line2.unit_price, Decimal('20.0000'))
