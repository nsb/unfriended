#!/usr/bin/env python
#
# Copyright 2010 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""A barebones AppEngine application that uses Facebook for login."""

FACEBOOK_APP_ID = "166274003408283"
FACEBOOK_APP_SECRET = "63a603a7707a3dda01daa0f78960c887"

import logging
import os.path
import wsgiref.handlers

import facebook

from google.appengine.api import taskqueue
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template


class User(db.Model):
    id = db.StringProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    name = db.StringProperty(required=True)
    profile_url = db.StringProperty(required=True)
    access_token = db.StringProperty(required=True)

class Friend(db.Model):
    id = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    user = db.ReferenceProperty(User)

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

class SyncFriendsWorker(webapp.RequestHandler):
    """
    To activate worker:
    curl --data-urlencode "key=<user.key_name>" http://unfriendster.appspot.com
    """
    def post(self):
        key = self.request.get('key')
        user = User.get_by_key_name(key)
        graph = facebook.GraphAPI(user.access_token)
        friends = graph.get_connections("me", "friends")["data"]
        friend_ids = set((f["id"] for f in friends))

        # check for unfriends
        for friend in user.friend_set:
            if friend.id not in friend_ids:
                logging.info('unfriend:%s' % friend.name)
            else:
                logging.info('friend:%s' % friend.name)

        # update all friends
        for friend in friends:
            def txn():
                f = Friend(
                    key_name=str(friend["id"]),
                    id=str(friend["id"]),
                    name=friend["name"],
                    user=user.key(),
                )
                f.put()
            db.run_in_transaction(txn)

class HomeHandler(BaseHandler):
    def get(self):
        path = os.path.join(os.path.dirname(__file__), "example.html")
        args = dict(current_user=self.current_user,
                    facebook_app_id=FACEBOOK_APP_ID)
        self.response.out.write(template.render(path, args))

    def post(self):
        key = self.request.get('key')

        # Add the task to the default queue.
        taskqueue.add(url='/syncfriends', params={'key': key})
        self.redirect('/')

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    util.run_wsgi_app(webapp.WSGIApplication([(r"/", HomeHandler), (r"/syncfriends", SyncFriendsWorker),]))

if __name__ == "__main__":
    main()
