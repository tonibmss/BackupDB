
from odoo import  tools, fields, models, _
import logging

from odoo.tools.misc import formatLang, format_date

log = logging.getLogger(__name__)


class AccountFollowupReport(models.AbstractModel):
    _inherit = "account.followup.report"
    
    def _get_lines(self, options, line_id=None):
        """
        Override
        Compute and return the lines of the columns of the follow-ups report.
        """
        # Get date format for the lang
        partner = options.get('partner_id') and self.env['res.partner'].browse(options['partner_id']) or False
        if not partner:
            return []

        lang_code = partner.lang if self._context.get('print_mode') else self.env.user.lang or get_lang(self.env).code
        lines = []
        res = {}
        today = fields.Date.today()
        line_num = 0
        for l in partner.unreconciled_aml_ids.filtered(lambda l: l.company_id == self.env.company):
            if l.company_id == self.env.company:
                if self.env.context.get('print_mode') and l.blocked:
                    continue
                currency = l.currency_id or l.company_id.currency_id
                if currency not in res:
                    res[currency] = []
                res[currency].append(l)
        for currency, aml_recs in res.items():
            total = 0
            total_issued = 0
            for aml in aml_recs:
                amount = aml.amount_residual_currency if aml.currency_id else aml.amount_residual
                date_due = format_date(self.env, aml.date_maturity or aml.date, lang_code=lang_code)
                total += not aml.blocked and amount or 0
                is_overdue = today > aml.date_maturity if aml.date_maturity else today > aml.date
                is_payment = aml.payment_id
                if is_overdue or is_payment:
                    total_issued += not aml.blocked and amount or 0
                if is_overdue:
                    date_due = {'name': date_due, 'class': 'color-red date', 'style': 'white-space:nowrap;text-align:center;color: red;'}
                if is_payment:
                    date_due = ''
                move_line_name =aml.name
                log.info("33333333 %s",move_line_name)
                if self.env.context.get('print_mode'):
                    move_line_name = {'name': move_line_name, 'style': 'text-align:right; white-space:normal;'}
                amount = formatLang(self.env, amount, currency_obj=currency)
                line_num += 1
                expected_pay_date = format_date(self.env, aml.expected_pay_date, lang_code=lang_code) if aml.expected_pay_date else ''
                invoice_origin = aml.move_id.invoice_origin or ''
                if len(invoice_origin) > 43:
                    invoice_origin = invoice_origin[:40] + '...'
                columns = [
                    format_date(self.env, aml.date, lang_code=lang_code),
                    date_due,
                    invoice_origin,
                    move_line_name,
                    (expected_pay_date and expected_pay_date + ' ') + (aml.internal_note or ''),
                    {'name': '', 'blocked': aml.blocked},
                    amount,
                ]
                if self.env.context.get('print_mode'):
                    columns = columns[:4] + columns[6:]
                lines.append({
                    'id': aml.id,
                    'account_move': aml.move_id,
                    'name': aml.move_id.name,
                    'caret_options': 'followup',
                    'move_id': aml.move_id.id,
                    'type': is_payment and 'payment' or 'unreconciled_aml',
                    'unfoldable': False,
                    'columns': [type(v) == dict and v or {'name': v} for v in columns],
                })
            total_due = formatLang(self.env, total, currency_obj=currency)
            line_num += 1
            lines.append({
                'id': line_num,
                'name': '',
                'class': 'total',
                'style': 'border-top-style: double',
                'unfoldable': False,
                'level': 3,
                'columns': [{'name': v} for v in [''] * (3 if self.env.context.get('print_mode') else 5) + [total >= 0 and _('Total Due') or '', total_due]],
            })
            if total_issued > 0:
                total_issued = formatLang(self.env, total_issued, currency_obj=currency)
                line_num += 1
                lines.append({
                    'id': line_num,
                    'name': '',
                    'class': 'total',
                    'unfoldable': False,
                    'level': 3,
                    'columns': [{'name': v} for v in [''] * (3 if self.env.context.get('print_mode') else 5) + [_('Total Overdue'), total_issued]],
                })
            # Add an empty line after the total to make a space between two currencies
            line_num += 1
            lines.append({
                'id': line_num,
                'name': '',
                'class': '',
                'style': 'border-bottom-style: none',
                'unfoldable': False,
                'level': 0,
                'columns': [{} for col in columns],
            })
        # Remove the last empty line
        if lines:
            lines.pop()
        return lines
    
class ResCurrency(models.Model):
    _inherit = 'res.currency'
    
    currency_unit_label_ids = fields.One2many('azk.currency.unit.label', 'currency_id')
    currency_subunit_label_ids = fields.One2many('azk.currency.sub.unit.label', 'currency_id')

     
    """
         1- function amount_to_text takes the default company language which is en_US.
         2- the solution for report is to use currecny_id.with_context(lang='lang_code').amount_to_text(amount)
    """
    def amount_to_text(self, amount):
        #
        temp_unit = self.currency_unit_label
        temp_subunit = self.currency_subunit_label
        
        if self._context.get('lang'):
            lang_code = self._context.get('lang')
            unit_label = self.currency_unit_label_ids.filtered(lambda c: c.langauge_code.code == lang_code).name
            if unit_label:
                self.currency_unit_label = unit_label
                
            subunit_label = self.currency_subunit_label_ids.filtered(lambda c: c.langauge_code.code == lang_code).name
            if subunit_label:
                self.currency_subunit_label = subunit_label
        
        result = super(ResCurrency, self).amount_to_text(amount)
        # keep original values since they can be read directly not via amount_to_text
        self.currency_unit_label = temp_unit
        self.currency_subunit_label = temp_subunit
        
        return result
           
    def open_curreny_unit_label_list(self):
        self.ensure_one()
        return {
            'name': _('Currency Unit label'),
            'view_mode': 'tree,form',
            'views': [(self.env.ref('az_amount_currency_text.view_currency_unit_label_tree').id, 'tree'), (False, 'form')],
            'res_model': 'azk.currency.unit.label',
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': [('currency_id', '=', self.id)],
            'context': {
                'default_currency_id': self.id,
            }
        }
    
    def open_curreny_sub_unit_label_list(self):
        self.ensure_one()
        return {
            'name': _('Currency Sub Unit label'),
            'view_mode': 'tree,form',
            'views': [(self.env.ref('az_amount_currency_text.view_currency_subunit_label_tree').id, 'tree'), (False, 'form')],
            'res_model': 'azk.currency.sub.unit.label',
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': [('currency_id', '=', self.id)],
            'context': {
                'default_currency_id': self.id,
            }
        }

class AzkCurrencyUnitlabel(models.Model):
    _name = 'azk.currency.unit.label'
    
    name = fields.Char('Currency Label', required=True)
    langauge_code = fields.Many2one('res.lang', string='Language', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    
class AzkCurrencySubUnitlabel(models.Model):
    _name = 'azk.currency.sub.unit.label'
    
    name = fields.Char('Currency Label', required=True)
    langauge_code = fields.Many2one('res.lang', string='Language', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
            