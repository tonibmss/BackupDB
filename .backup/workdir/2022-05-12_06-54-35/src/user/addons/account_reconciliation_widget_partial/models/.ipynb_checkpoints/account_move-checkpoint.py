
from odoo import fields, models

import logging
log = logging.getLogger(__name__)

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"   
    
    new_amount = fields.Monetary(string='New Amount', default=0.0, currency_field='company_currency_id')
    
    
    def _reconcile_lines(self, debit_moves, credit_moves, field): 
        value = 0
        if(self.env.context.get("move_lines")):
            move_lines = self.env.context.get("move_lines")
            for debit_move in debit_moves:
                value = move_lines.get(str(debit_move.id)).get("partial_amount") or 0
                if value:
                    break
            
            if not value:
                for credit_move in credit_moves:
                    value = move_lines.get(str(credit_move.id)).get("partial_amount") or 0
                    if value:
                        break
                
        if value:
            base_reconcile = "amount_residual"
            move_lines = self.env.context.get("move_lines")
            field = "new_amount"
            for debit_move in debit_moves:
                account = self.env["account.move.line"].browse(debit_move.id)
                value = move_lines.get(str(debit_move.id)).get("partial_amount") or account.amount_residual
                    
                account.update({"new_amount": abs(value)})
            for credit_move in credit_moves:
                account = self.env["account.move.line"].browse(credit_move.id)
                value = move_lines.get(str(credit_move.id)).get("partial_amount") or account.amount_residual
                account.update({"new_amount": abs(value)})
                
                
            
            (debit_moves + credit_moves).read([field])
            to_create = []
            cash_basis = debit_moves and debit_moves[0].account_id.internal_type in ('receivable', 'payable') or False
            cash_basis_percentage_before_rec = {}
            dc_vals ={}
            while (debit_moves and credit_moves):
                debit_move = debit_moves[0]
                credit_move = credit_moves[0]
                company_currency = debit_move.company_id.currency_id
                # We need those temporary value otherwise the computation might be wrong below
                temp_amount_residual = min(abs(debit_move.new_amount), abs(credit_move.new_amount))
                if base_reconcile == "amount_residual_currency":
                    date = max(debit_move.date, credit_move.date)
                    temp_amount_residual_currency = company_currency._convert(temp_amount_residual, debit_move.currency_id, debit_move.company_id, date)
                else:
                    temp_amount_residual_currency = temp_amount_residual
                
                amount_to_delete = temp_amount_residual
                dc_vals[(debit_move.id, credit_move.id)] = (debit_move, credit_move, temp_amount_residual_currency)
                
                
                if temp_amount_residual == debit_move[field]:
                    debit_moves -= debit_move
                else:
                    debit_moves[0].amount_residual -= abs(temp_amount_residual)
                    debit_moves[0].amount_residual_currency -= abs(temp_amount_residual_currency)
                    debit_moves[0].new_amount -= abs(temp_amount_residual)
        
                if temp_amount_residual == credit_move[field]:
                    credit_moves -= credit_move
                else:
                    credit_moves[0].amount_residual += abs(temp_amount_residual)
                    credit_moves[0].amount_residual_currency += abs(temp_amount_residual_currency)
                    credit_moves[0].new_amount -= abs(temp_amount_residual)
                currency = False
                amount_reconcile_currency = 0
                if base_reconcile == 'amount_residual_currency':
                    currency = credit_move.currency_id.id
                    amount_reconcile_currency = temp_amount_residual_currency
                    amount_reconcile = temp_amount_residual
                elif bool(debit_move.currency_id) != bool(credit_move.currency_id):
                    currency = debit_move.currency_id or credit_move.currency_id
                    currency_date = debit_move.currency_id and credit_move.date or debit_move.date
                    amount_reconcile = temp_amount_residual
                    amount_reconcile_currency = company_currency._convert(amount_reconcile, currency, debit_move.company_id, currency_date)
                    currency = currency.id
                else:
                    amount_reconcile = temp_amount_residual
                    amount_reconcile_currency = temp_amount_residual_currency
    
                if cash_basis:
                    tmp_set = debit_move | credit_move
                    cash_basis_percentage_before_rec.update(tmp_set._get_matched_percentage())
    
                to_create.append({
                    'debit_move_id': debit_move.id,
                    'credit_move_id': credit_move.id,
                    'amount': amount_reconcile,
                    'amount_currency': amount_reconcile_currency,
                    'currency_id': currency,
                })
                
            cash_basis_subjected = []
            part_rec = self.env['account.partial.reconcile']
            for partial_rec_dict in to_create:
                debit_move, credit_move, amount_residual_currency = dc_vals[partial_rec_dict['debit_move_id'], partial_rec_dict['credit_move_id']]
                # /!\ NOTE: Exchange rate differences shouldn't create cash basis entries
                # i. e: we don't really receive/give money in a customer/provider fashion
                # Since those are not subjected to cash basis computation we process them first
                if not amount_residual_currency and debit_move.currency_id and credit_move.currency_id:
                    part_rec.create(partial_rec_dict)
                else:
                    cash_basis_subjected.append(partial_rec_dict)
    
            for after_rec_dict in cash_basis_subjected:
                new_rec = part_rec.create(after_rec_dict)
                # if the pair belongs to move being reverted, do not create CABA entry
                if cash_basis and not (
                        new_rec.debit_move_id.move_id == new_rec.credit_move_id.move_id.reversed_entry_id
                        or
                        new_rec.credit_move_id.move_id == new_rec.debit_move_id.move_id.reversed_entry_id
                ):
                    new_rec.create_tax_cash_basis_entry(cash_basis_percentage_before_rec)
            return debit_moves+credit_moves

        else:               
            return super(AccountMoveLine, self)._reconcile_lines(debit_moves, credit_moves, field)
        