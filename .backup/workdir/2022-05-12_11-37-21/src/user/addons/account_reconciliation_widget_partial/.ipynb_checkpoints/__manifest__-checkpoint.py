{
    'name': 'Account Reconciliation Widget Partial',
    'summary': """
        Allow to modifiy the reconcile amount for partial payments""",
    'version': '13.0.0.0.2',
    'license': 'AGPL-3',
    'author': 'Azkatech',
    'website': 'https://azka.tech',
    'depends': [
        'lb_accounting',
    ],
    'data': [
        'views/assets.xml',
    ],
    'qweb': [
        'static/src/xml/account_reconciliation.xml',
    ],
}
