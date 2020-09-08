from flask import (Blueprint, flash, redirect, render_template, request)

from authentication import admin_authentication
from database.user_models import Researcher

login_pages = Blueprint('login_pages', __name__)


@login_pages.route('/')
def render_login_page():
    if admin_authentication.is_logged_in():
        return redirect("/choose_study")
    return render_template('admin_login.html')


@login_pages.route("/validate_login", methods=["GET", "POST"])
def login():
    """ Authenticates administrator login, redirects to login page if authentication fails. """
    if request.method == 'POST':
        username = request.values["username"]
        password = request.values["password"]
        if Researcher.check_password(username, password):
            admin_authentication.log_in_researcher(username)
            return redirect("/choose_study")
        else:
            flash("Incorrect username & password combination; try again.", 'danger')

    return redirect("/")
