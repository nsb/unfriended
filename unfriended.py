#!/usr/bin/env python

"""Get notifications when unfriended on Facebook"""

# prod
FACEBOOK_APP_ID = "166274003408283"
FACEBOOK_APP_KEY = "c29e42b8ebf58e101fef32e4b8564130"
FACEBOOK_APP_SECRET = "63a603a7707a3dda01daa0f78960c887"

# devel
#FACEBOOK_APP_ID = "166334160087044"
#FACEBOOK_APP_KEY = "6bb2ee2d8e51a10fae9f29f6f2919ee7"
#FACEBOOK_APP_SECRET = "29e0bee7514bf75ffdd7ff42622b7d04"

import urllib2
import logging
import os.path
import wsgiref.handlers

import facebook

from google.appengine.api import taskqueue
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from google.appengine.api import mail

class User(db.Model):
    id = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    name = db.StringProperty(required=True)
    profile_url = db.StringProperty(required=True)
    access_token = db.StringProperty(required=True)
    email = db.EmailProperty(required=False)
    active = db.BooleanProperty(default=False)

class Friend(db.Model):
    id = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    unfriended = db.BooleanProperty(default=False)
    user = db.ReferenceProperty(User, collection_name='friends')

class BaseHandler(webapp.RequestHandler):
    """Provides access to the active Facebook user in self.current_user

    The property is lazy-loaded on first access, using the cookie saved
    by the Facebook JavaScript SDK to determine the user ID of the active
    user. See http://developers.facebook.com/docs/authentication/ for
    more information.
    """
    @property
    def current_user(self):
        if not hasattr(self, "_current_user"):
            self._current_user = None
            cookie = facebook.get_user_from_cookie(
                self.request.cookies, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET)
            if cookie:
                # Store a local instance of the user data so we don't need
                # a round-trip to Facebook on every request
                user = User.get_by_key_name(cookie["uid"])
                if not user:
                    graph = facebook.GraphAPI(cookie["access_token"])
                    profile = graph.get_object("me")
                    user = User(key_name=str(profile["id"]),
                                id=str(profile["id"]),
                                name=profile["name"],
                                profile_url=profile["link"],
                                access_token=cookie["access_token"])
                    user.put()
                elif user.access_token != cookie["access_token"]:
                    user.access_token = cookie["access_token"]
                    user.put()
                self._current_user = user
        return self._current_user

class NotifyUnfriendedWorker(webapp.RequestHandler):
    """
    Notify on unfriended
    """
    def post(self):
        key = self.request.get('key')
        friend = Friend.get(key)
        friend.unfriended= True
        friend.put()
        mail.send_mail(
            'notifications@unfriendster.appspotmail.com',
            friend.user.email,
            'unfriended: %s' % friend.name,
            'sucks',
        )
        logging.info('%s and %s are no longer friends' % (friend.user.name, friend.name))

class SyncFriendsWorker(webapp.RequestHandler):
    """
    To activate worker:
    curl --data-urlencode "key=<user.key_name>" http://unfriendster.appspot.com
    """
    def post(self):
        key = self.request.get('key')
        user = User.get_by_key_name(key)
        graph = facebook.GraphAPI(user.access_token)
        try:
            friends = graph.get_connections("me", "friends")["data"]
        except urllib2.HTTPError, e:
            logging.error('Error getting friend connections for %s' % user.name)
            return

        friend_ids = set((f["id"] for f in friends))

        # update all friends
        for friend in friends:
            key_name = str(friend["id"])
            f = Friend.get_or_insert(key_name, parent=user, id=str(friend["id"]),
                                     user=user.key(), name=friend["name"])

        # check for unfriends
        for friend in user.friends.filter("unfriended =", False):
            if friend.id not in friend_ids:
                taskqueue.add(url='/notifyunfriended', params={'key': friend.key()})

class SyncUsersWorker(webapp.RequestHandler):
    """
    To activate worker:
    curl --data-urlencode "" http://unfriendster.appspot.com/syncusers
    """
    def get(self):
        for user in User.all():
            taskqueue.add(url='/syncfriends', params={'key': user.id})

class HomeHandler(BaseHandler):
    def get(self):
        path = os.path.join(os.path.dirname(__file__), "example.html")
        args = dict(current_user=self.current_user,
                    facebook_app_id=FACEBOOK_APP_ID)
        self.response.out.write(template.render(path, args))

    def post(self):

        key = self.request.get('key')
        if key:
            taskqueue.add(url='/syncfriends', params={'key': key})

        email = self.request.get('email')
        if mail.is_email_valid(email):
            self.current_user.email = email
            self.current_user.active = True
            self.current_user.put()

        self.redirect('/')

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    util.run_wsgi_app(webapp.WSGIApplication([
        (r"/", HomeHandler),
        (r"/syncusers", SyncUsersWorker),
        (r"/syncfriends", SyncFriendsWorker),
        (r"/notifyunfriended", NotifyUnfriendedWorker),
    ]))

if __name__ == "__main__":
    main()
