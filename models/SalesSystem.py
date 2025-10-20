from odoo.exceptions import ValidationError
from odoo import fields, models, api


class Customer(models.Model):
    _name = 'customer.custom'
    _description = 'Customers'

    name = fields.Char(string='Name', required=True)
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    address = fields.Char(string='Address')
    customer_type = fields.Selection([
        ('retail', 'Retail'), ('wholesale', 'Wholesale'), ('company', 'Company'),
    ], string='Customer Type', default='retail', required=True)
    sale_ids = fields.One2many('sale.order.custom', 'customer_id', string='Sale Orders')


class Product(models.Model):
    _name = 'product.custom'
    _description = 'Products'
    _rec_name = 'product_code'

    inventory_id = fields.Many2one('inventory.custom', string='Inventory Item', required=True)
    name = fields.Selection(related='inventory_id.name', string='Product Name', readonly=True)
    product_code = fields.Selection(related='inventory_id.product_code', string='Product Code', readonly=True)
    product_price = fields.Float(related='inventory_id.product_price', string='Product Price', readonly=True)
    unit = fields.Selection(related='inventory_id.unit', string='Unit', readonly=True)
    production_date = fields.Date(string='Production Date')
    expiration_date = fields.Date(string='Expiration Date')

    @api.model
    def create(self, vals):
        product = super(Product, self).create(vals)
        if product.inventory_id:
            product.inventory_id._compute_quantities()
        return product

    def unlink(self):
        inventory_records = self.mapped('inventory_id')
        result = super(Product, self).unlink()
        for inventory in inventory_records:
            inventory._compute_quantities()
        return result


class Inventory(models.Model):
    _name = 'inventory.custom'
    _description = 'Inventory'
    _rec_name = 'product_code'

    name = fields.Selection([
        ('milk', 'Milk'),
        ('cheese', 'Cheese'),
        ('yogurt', 'Yogurt'),
        ('cream', 'Cream'),
        ('butter', 'Butter'), ],
        string='Product Name',
        required=True)

    product_code = fields.Selection([
        ('MILK001', 'MILK001'),
        ('CHS001', 'CHS001'),
        ('YGT001', 'YGT001'),
        ('CRM001', 'CRM001'),
        ('BTR001', 'BTR001'), ],
        string='Product Code',
        required=True)

    product_price = fields.Float(string='Product Price', required=True)
    unit = fields.Selection([('kg', 'Kg'), ('ib', 'Ib')], string='Unit', required=True)

    quantity_available = fields.Integer(string='Available Quantity', compute='_compute_quantities', store=True)
    sold_quantity = fields.Integer(string='Sold Quantity', compute='_compute_quantities', store=True)

    @api.depends('product_code')
    def _compute_quantities(self):
        for inventory in self:
            products_count = self.env['product.custom'].search_count([
                ('product_code', '=', inventory.product_code)
            ])
            sold_lines = self.env['historical.sale.lines'].search([
                ('product_code', '=', inventory.product_code)
            ])
            total_sold = sum(sold_lines.mapped('quantity'))
            inventory.sold_quantity = total_sold
            inventory.quantity_available = products_count - total_sold

    @api.onchange('product_code')
    def _onchange_product_code(self):
        code_name_mapping = {
            'MILK001': 'milk',
            'CHS001': 'cheese',
            'YGT001': 'yogurt',
            'CRM001': 'cream',
            'BTR001': 'butter',
        }
        for inventory in self:
            if inventory.product_code:
                inventory.name = code_name_mapping.get(inventory.product_code)

    _sql_constraints = [
        ('product_code_unique', 'unique(product_code)', 'Product code must be unique!'),
    ]


class SaleOrder(models.Model):
    _name = 'sale.order.custom'
    _description = 'Sales Orders'

    ref = fields.Char(string='Reference', readonly=True, default='New')
    sale_date = fields.Datetime(default=fields.Datetime.now, readonly=True)

    order_lines = fields.One2many('sale.lines', 'sale_id', string='Order Lines', required=True)
    total_amount = fields.Float(string='Total Amount', compute='_compute_totals', store=True)
    total_quantity = fields.Integer(string='Total Quantity', compute='_compute_totals', store=True)

    customer_id = fields.Many2one('customer.custom', string='Customer', required=True)
    customer_phone = fields.Char(related='customer_id.phone', string='Customer Phone')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Successful'),
        ('canceled', 'Canceled')],
        string='Status', default='draft')

    def action_cancel(self):
        for order in self:
            order.state = 'canceled'

    @api.depends('order_lines.amount', 'order_lines.quantity')
    def _compute_totals(self):
        for order in self:
            total_amount = 0.0
            total_quantity = 0
            for line in order.order_lines:
                total_amount += line.amount
                total_quantity += line.quantity
            order.total_amount = total_amount
            order.total_quantity = total_quantity

    def action_done(self):
        for order in self:
            if not order.order_lines:
                raise ValidationError("You have to add one product at least before confirming the order.")
            order.state = 'done'

            order._archive_sales_to_history(order)

            inventory_records = self.env['inventory.custom'].search([])
            for inventory in inventory_records:
                inventory._compute_quantities()

            for line in order.order_lines:
                product = line.product_id
                qty = int(line.quantity)
                if not product or not product.product_code:
                    continue

                custom_records = self.env['product.custom'].search([
                    ('product_code', '=', product.product_code)
                ], limit=qty)

                if custom_records:
                    custom_records.unlink()
                else:
                    print(f"There is no enough records to delete {product.product_code}")

            inventory_records = self.env['inventory.custom'].search([])
            for inventory in inventory_records:
                inventory._compute_quantities()

    def _archive_sales_to_history(self, order):
        existing_record = self.env['historical.sales'].search([('ref', '=', order.ref)])
        if existing_record:
            existing_record.unlink()

        historical_sale = self.env['historical.sales'].create({
            'ref': order.ref,
            'sale_date': order.sale_date,
            'customer_name': order.customer_id.name,
            'customer_email': order.customer_id.email,
            'customer_phone': order.customer_id.phone,
        })

        for line in order.order_lines:
            self.env['historical.sale.lines'].create({
                'historical_sale_id': historical_sale.id,
                'product_name': line.product_id.name,
                'product_code': line.product_id.product_code,
                'quantity': line.quantity,
                'unit_price': line.product_price,
                'total_amount': line.amount,
            })

    @api.model
    def create(self, vals):
        if vals.get('ref', 'New') == 'New':
            vals['ref'] = self.env['ir.sequence'].next_by_code('sale_seq')
        return super(SaleOrder, self).create(vals)


class SaleOrderLine(models.Model):
    _name = 'sale.lines'
    _description = 'Sale Order Lines'

    sale_id = fields.Many2one('sale.order.custom', string='Sale Order', required=True, ondelete='cascade')

    product_id = fields.Many2one('product.custom', string='Product', required=True, ondelete='cascade')
    name = fields.Selection(related='product_id.name', string='Product Name', readonly=True)
    product_code = fields.Selection(related='product_id.product_code', string='Product Code', readonly=True)

    product_price = fields.Float(related='product_id.product_price', string='Product Price', readonly=True)
    quantity = fields.Integer(string='Quantity', required=True, default=1)
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)
    available_qty = fields.Integer(related='product_id.inventory_id.quantity_available', string='Available Quantity', readonly=True)

    @api.depends('quantity', 'product_price')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.product_price

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Must be grater than zero!")

            if line.quantity > line.available_qty and line.sale_id.state != 'canceled':
                raise ValidationError(
                    f"Not enough quantity available for {line.product_code}. "
                    f"Available: {line.available_qty}, Requested: {line.quantity}"
                )


class HistoricalSales(models.Model):
    _name = 'historical.sales'
    _description = 'Historical Sales'
    _rec_name = 'ref'
    _order = 'sale_date desc'

    ref = fields.Char(string='Reference', readonly=True)
    sale_date = fields.Datetime(string='Sale Date', readonly=True)

    sale_line_ids = fields.One2many('historical.sale.lines', 'historical_sale_id', string='Orders', readonly=True)

    customer_name = fields.Char(string='Customer Name', readonly=True)
    customer_email = fields.Char(string='Customer Email', readonly=True)
    customer_phone = fields.Char(string='Customer Phone', readonly=True)
    archived_date = fields.Datetime(string='Archived Date', default=fields.Datetime.now, readonly=True)

    total_quantity = fields.Integer(string='Total Quantity', compute='_compute_totals', store=True)
    total_amount = fields.Float(string='Total Amount', compute='_compute_totals', store=True)

    @api.depends('sale_line_ids.quantity', 'sale_line_ids.total_amount')
    def _compute_totals(self):
        for record in self:
            record.total_quantity = sum(record.sale_line_ids.mapped('quantity'))
            record.total_amount = sum(record.sale_line_ids.mapped('total_amount'))


class HistoricalSaleLines(models.Model):
    _name = 'historical.sale.lines'
    _description = 'Historical Sale Lines'

    historical_sale_id = fields.Many2one('historical.sales', string='Historical Sale', required=True, ondelete='cascade')

    product_name = fields.Selection([
        ('milk', 'Milk'),
        ('cheese', 'Cheese'),
        ('yogurt', 'Yogurt'),
        ('cream', 'Cream'),
        ('butter', 'Butter'),],
        string='Product Name', readonly=True)

    product_code = fields.Selection([
        ('MILK001', 'MILK001'),
        ('CHS001', 'CHS001'),
        ('YGT001', 'YGT001'),
        ('CRM001', 'CRM001'),
        ('BTR001', 'BTR001'),],
        string='Product Code', readonly=True)

    quantity = fields.Integer(string='Quantity', readonly=True)
    unit_price = fields.Float(string='Unit Price', readonly=True)
    total_amount = fields.Float(string='Total Amount', readonly=True)
