import datetime
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

log = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    state = fields.Selection(selection_add=[("confirmed", "Confirmed"),("posted",)])
    product_ids = fields.Many2one(
        "product.product", related="invoice_id.invoice_line_ids.product_id"
    )
    invoice_id = fields.Many2one("account.move")
    dest_location = fields.Many2one("stock.location")
    location_id = fields.Many2one("stock.location")
    bill_id = fields.Many2one("account.move")
    delivery_count = fields.Integer(compute="_compute_delivery_count")
    show_post = fields.Boolean(compute="_compute_show_post")
    
    def _compute_show_post(self):
        for rec in self:
            rec.show_post = False
            if rec.type in ('out_refund','in_refund') and rec.state == 'confirmed' and not rec.auto_post and not rec.invoice_origin:
                rec.show_post = True
            
    def button_draft(self):
        res = super(AccountMove, self).button_draft()
        if self.id:
            pickings = self.env['stock.picking'].search([('credit_note_id', '=', self.id)])
            if pickings:
                pickings.action_cancel()
        return res 
    
    def action_view_delivery(self):
        """
            View deliveries of the refund
        """
        action = self.env.ref('stock.action_picking_tree_all').read()[0]

        pickings = self.env['stock.picking'].search([('credit_note_id', '=', self.id)])
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            form_view = [(self.env.ref('stock.view_picking_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state,view) for state,view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = pickings.id
        # Prepare the context.
        picking_id = pickings.filtered(lambda l: l.picking_type_id.code == 'outgoing')
        if picking_id:
            picking_id = picking_id[0]
        else:
            picking_id = pickings[0]
        action['context'] = dict(self._context, default_partner_id=self.partner_id.id, default_picking_id=picking_id.id, default_picking_type_id=picking_id.picking_type_id.id, default_origin=self.name, default_group_id=picking_id.group_id.id)
        return action
    
    def _compute_delivery_count(self):
        pickings = self.env["stock.picking"].search([("credit_note_id", "=", self.id)])
        self.delivery_count = len(pickings)

    def is_credit(self):
        if self.type == "out_refund" or self.type == "in_refund":
            return True
        else:
            return False
    
    @api.onchange("bill_id")
    def on_change_bill(self):
        if self.type == "in_refund":
            self.invoice_id = self.bill_id
            self._onchange_invoice()
        
    def check_tax_validity(self):
        """
            for each tax in each line check if the tax expired
        """
        message = ""
        is_not_valid = False
        if not self.invoice_id:
            return True
        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                if self.invoice_date:
                    if (
                        tax.allowed_days_to_be_return
                        < (self.invoice_date - self.invoice_id.invoice_date).days
                    ):
                        if tax.name not in message:
                            message += tax.name
                        is_not_valid = True
                else:
                    if (
                        tax.allowed_days_to_be_return
                        < (datetime.date.today() - self.invoice_id.invoice_date).days
                    ):
                        if tax.name not in message:
                            message += tax.name
                        is_not_valid = True
        if is_not_valid:
            message = "These Taxes can't be applied here: " + message
            raise ValidationError(message)

    @api.model
    def create(self, vals):
        """
            check only for credit notes
        """
        res = super(AccountMove, self).create(vals)
        if res.is_credit():
            res.check_tax_validity()

        return res

    def write(self, vals):
        """
            check only for credit notes
        """
        res = super(AccountMove, self).write(vals)
        for rec in self:
            if rec.is_credit():
                rec.check_tax_validity()

        return res

    
    def _reverse_move_vals(self, default_values, cancel=True):
        res = super(AccountMove,self)._reverse_move_vals(default_values, cancel)
        if 'invoice_id' not in default_values:
            return res
        for line in res['line_ids']:
            taxes = line[2]['tax_ids'][0]
            basic_invoice = self.env["account.move"].browse(default_values['invoice_id'])
            if basic_invoice:
                accepted_tax = []
                for tax_id in taxes[2]:
                    tax = self.env["account.tax"].browse(tax_id)
                    if tax.allowed_days_to_be_return >= (default_values['date'] - basic_invoice.invoice_date ).days:
                        accepted_tax.append(tax_id)
                lst = list(line[2]['tax_ids'][0])
                lst[0] = 6
                lst[1] = 6
                
                lst[2] = accepted_tax
                t = tuple(lst)
                line[2]['tax_ids'][0] = t
        return res  
    
    def action_confirm(self):
        """
        When confirm credit note make new transfer
            check if the credit note empty lines no transfer to create
            check if the credit note has service products lines don't dd them
        """
        if not self.line_ids.filtered(lambda line: not line.display_type):
            raise UserError(_("You need to add a line before confirming."))
        need_to_create_transfer = False
        for line in self.invoice_line_ids:
            if line.product_id.type == "product":
                need_to_create_transfer = True
        self.check_tax_validity()

        to_write = {"state": "confirmed"}

        self.write(to_write)
        move_type = self.type
        picking_in = None

        if move_type == "out_refund":
            location_dest_id = self.dest_location.id
            location_id = self.partner_id.property_stock_supplier.id
            picking_type = self.env["stock.picking.type"].search([("company_id", "=", self.company_id.id), ("code", "=", "incoming")],limit=1).id
        else:
            location_id = self.location_id.id
            location_dest_id = self.partner_id.property_stock_supplier.id
            picking_type = self.env["stock.picking.type"].search([('company_id','=',self.company_id.id),('code','=','outgoing')],limit=1).id
        
        if need_to_create_transfer:
            StockPicking = self.env["stock.picking"]
            picking_in = StockPicking.sudo().create(
                {
                    "partner_id": self.partner_id.id,
                    "user_id": self.user_id.id,
                    "company_id": self.company_id.id,
                    "date": self.date,
                    "origin": self.name,
                    "picking_type_id": picking_type,
                    "location_id": location_id,
                    "location_dest_id": location_dest_id,
                    'move_type':'direct'
                }
            )

            for line in self.invoice_line_ids:
                if line.product_id.type == "product":
                    self.env["stock.move"].create(
                        {
                            "name": line.name,
                            "location_dest_id": location_dest_id,
                            "location_id": location_id,
                            "picking_id": picking_in.id,
                            "product_id": line.product_id.id,
                            "product_uom": line.product_id.uom_id.id,
                            "product_uom_qty": line.quantity,
                        }
                    )
            picking_in.credit_note_id = self.id
            picking_in.action_confirm()

        to_write = {"state": "confirmed"}
        self.write(to_write)

        if picking_in:
            action = self.env.ref("stock.stock_picking_action_picking_type").read()[0]
            form_view = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["views"] = form_view
            action["res_id"] = picking_in.id

            return action

    @api.onchange("invoice_id", "bill_id")
    def _onchange_invoice(self):
        """
        When change invoice create lines in the credit note from invoice lines
            for all taxes check which tax not expired and add it
        apply all function calls when change lines to compute total and subtotal , ...
        """
        self.invoice_line_ids = [(6, False, [])]
        new_lines = []
        for line in self.invoice_id.invoice_line_ids:
            taxes = line.tax_ids
            for tax in line.tax_ids:
                if self.invoice_date:
                    if (
                        tax.allowed_days_to_be_return
                        <= (self.invoice_date - self.invoice_id.invoice_date).days
                    ):
                        taxes -= tax
                else:
                    if (
                        tax.allowed_days_to_be_return
                        <= (datetime.date.today() - self.invoice_id.invoice_date).days
                    ):
                        taxes -= tax

            new_lines += [
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "name": line.name,
                        "company_id": line.company_id.id,
                        "product_uom_id": line.product_uom_id.id,
                        "account_id": line.account_id.id,
                        "quantity": line.quantity,
                        "currency_id":line.currency_id.id,
                        "price_unit": line.price_unit,
                        "discount": line.discount,
                        "tax_ids": taxes,
                        "price_subtotal": line.price_subtotal,
                    },
                )
            ]

        self.invoice_line_ids = new_lines

        for line in self.invoice_line_ids:
            if not line.move_id.is_invoice(include_receipts=True):
                continue

            line.update(line._get_price_total_and_subtotal())
            line.update(line._get_fields_onchange_subtotal())

        for line in self.invoice_line_ids:
            line.price_unit = line._get_computed_price_unit()

        # See '_onchange_product_id' for details.

        for line in self.invoice_line_ids:
            taxes = line._get_computed_taxes()
            price_unit = line._get_computed_price_unit()

            if taxes and line.move_id.fiscal_position_id:
                price_subtotal = line._get_price_total_and_subtotal(
                    price_unit=price_unit, taxes=taxes
                )["price_subtotal"]
                accounting_vals = line._get_fields_onchange_subtotal(
                    price_subtotal=price_subtotal, currency=line.move_id.company_currency_id
                )
                balance = accounting_vals["debit"] - accounting_vals["credit"]
                price_unit = line._get_fields_onchange_balance(balance=balance).get(
                    "price_unit", price_unit
                )

                # Convert the unit price to the invoice's currency.
                company = self.move_id.company_id
                line.price_unit = company.currency_id._convert(
                    price_unit, line.move_id.currency_id, company, line.move_id.date
                )

        for line in self.invoice_line_ids:
            if line.debit:
                line.credit = 0.0
            line._onchange_balance()

        for line in self.invoice_line_ids:
            if not line.tax_repartition_line_id:
                line.recompute_tax_line = True

        current_invoice_lines = self.line_ids.filtered(
            lambda line: not line.exclude_from_invoice_tab
        )
        others_lines = self.line_ids - current_invoice_lines
        if others_lines and current_invoice_lines - self.invoice_line_ids:
            others_lines[0].recompute_tax_line = True
        self.line_ids = others_lines + self.invoice_line_ids
        self._onchange_recompute_dynamic_lines()

        self._recompute_dynamic_lines()

        for line in self.invoice_line_ids:
            if not line.currency_id:
                continue
            if not line.move_id.is_invoice(include_receipts=True):
                line._recompute_debit_credit_from_amount_currency()
                continue
            line.update(line._get_fields_onchange_balance(amount_currency=line.amount_currency,))
            line.update(line._get_price_total_and_subtotal())

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """
            clear selected invoice when change partner id
        """
        res = super(AccountMove, self)._onchange_partner_id()
        if self.is_credit():
            self.invoice_line_ids = [(6, False, [])]
            self.invoice_id = False
        return res

    def action_custom_post(self):
        """
        Credit Note can't be posted before validate transfer
        """
        if self.is_credit():
            picking = self.env["stock.picking"].search(
                [("credit_note_id", "=", self.id)], order="id asc", limit=1
            )
            if picking.state == "done" or not picking:
                super(AccountMove, self).action_post()
            else:
                message = "Can't be posted before validate the transfer"
                raise ValidationError(message)
        else:
            super(AccountMove, self).action_post()

            

class StockPicking(models.Model):
    _inherit = "stock.picking"
    credit_note_id = fields.Many2one("account.move")

    def action_done(self):
        """
            Check if done quantity not equals to related credit note quantity raise error
        """
        if self.credit_note_id:
            for line in self.move_ids_without_package:
                if line.product_uom_qty != line.quantity_done:
                    message = "Done Quantity should be equals to Credit note line quantity"
                    raise ValidationError(message)

        super(StockPicking, self).action_done()


class AccountMoveReversal(models.TransientModel):
    _inherit = "account.move.reversal"

    def _prepare_default_reversal(self, move):
        res = super(AccountMoveReversal, self)._prepare_default_reversal(move)
        res['invoice_user_id'] = move.invoice_user_id.id
        res['invoice_id'] = move.id
        res['bill_id'] = move.id
        return res
        