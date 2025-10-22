from odoo import models, fields, api

class NileDairyDashboard(models.Model):
    _name = "nile.dairy.dashboard"
    _description = "Nile Dairy Dashboard"


    name = fields.Char(default="Dashboard", required=True, readonly=True)

    @api.model
    def get_default_dashboard_id(self):
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({'name': 'Dashboard'})
        return dashboard.id