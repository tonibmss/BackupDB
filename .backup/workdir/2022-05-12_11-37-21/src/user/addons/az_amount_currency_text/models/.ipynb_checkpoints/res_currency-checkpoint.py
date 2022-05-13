
from odoo import  tools, fields, models, _
import logging

log = logging.getLogger(__name__)

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
            