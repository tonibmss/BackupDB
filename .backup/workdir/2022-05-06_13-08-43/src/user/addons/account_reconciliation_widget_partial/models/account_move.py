
from odoo import fields, models,_
from werkzeug import url_encode

from odoo.tools import float_compare,float_is_zero

import logging
log = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"   
    
    def _get_cash_basis_matched_percentage(self):
        """Compute the percentage to apply for cash basis method. This value is relevant only for moves that
        involve journal items on receivable or payable accounts.
        """
        self.ensure_one()
        query = '''
            SELECT
            (
                SELECT COALESCE(SUM(line.balance), 0.0)
                FROM account_move_line line
                JOIN account_account account ON account.id = line.account_id
                JOIN account_account_type account_type ON account_type.id = account.user_type_id
                WHERE line.move_id = %s AND account_type.type IN ('receivable', 'payable')
            ) AS total_amount,
            (
                SELECT COALESCE(SUM(partial.amount), 0.0)
                FROM account_move_line line
                JOIN account_account account ON account.id = line.account_id
                JOIN account_account_type account_type ON account_type.id = account.user_type_id
                LEFT JOIN account_partial_reconcile partial ON
                    partial.debit_move_id = line.id
                    OR
                    partial.credit_move_id = line.id
                WHERE line.move_id = %s AND account_type.type IN ('receivable', 'payable')
            ) AS total_reconciled
        '''
        params = [self.id, self.id]
        self._cr.execute(query, params)
        total_amount, total_reconciled = self._cr.fetchone()
        log.info("0000000000000000000000000111 total_amount %s and total_reconciled %s",total_amount,total_reconciled)
        currency = self.company_id.currency_id
        if float_is_zero(total_amount, precision_rounding=currency.rounding):
            return 1.0
        else:
            return abs(currency.round(total_reconciled) / currency.round(total_amount))

        
class HrExpenseSheetRegisterPaymentWizard(models.TransientModel):
    _inherit = "hr.expense.sheet.register.payment.wizard"
    
    def expense_post_payment(self):
        log.info("0000000000000000")
        self.ensure_one()
        company = self.company_id
        self = self.with_context(force_company=company.id, company_id=company.id)
        context = dict(self._context or {})
        active_ids = context.get('active_ids', [])
        expense_sheet = self.env['hr.expense.sheet'].browse(active_ids)

        # Create payment and post it
        payment = self.env['account.payment'].create(self._get_payment_vals())
        payment.post()

        # Log the payment in the chatter
        body = (_("A payment of %s %s with the reference <a href='/mail/view?%s'>%s</a> related to your expense %s has been made.") % (payment.amount, payment.currency_id.symbol, url_encode({'model': 'account.payment', 'res_id': payment.id}), payment.name, expense_sheet.name))
        expense_sheet.message_post(body=body)

        # Reconcile the payment and the expense, i.e. lookup on the payable account move lines
        log.info("0000000000000000000000000111 payment.move_line_ids %s",payment.move_line_ids)
        log.info("0000000000000000000000000111 expense_sheet.account_move_id.line_ids %s",expense_sheet.account_move_id.line_ids)
        account_move_lines_to_reconcile = self._prepare_lines_to_reconcile(payment.move_line_ids + expense_sheet.account_move_id.line_ids)
        log.info("0000000000000000000000000111 account_move_lines_to_reconcile %s",account_move_lines_to_reconcile)
        account_move_lines_to_reconcile.reconcile()

        return {'type': 'ir.actions.act_window_close'}
    
class AccountMoveLine(models.Model):
    _inherit = "account.move.line"   
    
    new_amount = fields.Monetary(string='New Amount', default=0.0, currency_field='company_currency_id')
    
    def reconcile(self, writeoff_acc_id=False, writeoff_journal_id=False):
        #log.info("0000000000000000000000000111 %s",self)
        res = super(AccountMoveLine, self).reconcile(writeoff_acc_id=writeoff_acc_id, writeoff_journal_id=writeoff_journal_id)
        #log.info("0000000000000000000000000111 %s",self)
        for temp_line in self:
            log.info("0000000000000000000000000111")
            log.info("0000000000000000000000000 %s",temp_line.move_id._get_cash_basis_matched_percentage())
        account_move_ids = [l.move_id.id for l in self if float_compare(l.move_id._get_cash_basis_matched_percentage(), 1, precision_digits=5) != -1]
        log.info("0000000000000000000000000111 %s",account_move_ids)
        if account_move_ids:
            expense_sheets = self.env['hr.expense.sheet'].search([
                ('account_move_id', 'in', account_move_ids), ('state', '!=', 'done')
            ])
            expense_sheets.set_to_paid()
        return res
    
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
        