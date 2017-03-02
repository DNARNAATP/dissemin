# -*- encoding: utf-8 -*-

# Dissemin: open access policy enforcement tool
# Copyright (C) 2014 Antonin Delpeuch
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#


from __future__ import unicode_literals

import traceback

from django.conf import settings
from django.utils.translation import ugettext as __
from papers.baremodels import BareOaiRecord
from deposit.forms import BaseMetadataForm
from deposit.models import DEPOSIT_STATUS_CHOICES

class DepositError(Exception):
    """
    The exception to raise when something wrong happens
    during the deposition process
    """
    pass

class DepositResult(object):
    """
    Small object containing the result of a deposition process.
    This object will be stored in two rows in the database:
    in a BareOaiRecord and in a DepositRecord.

    status should be one of DEPOSIT_STATUS_CHOICES
    """

    def __init__(self, identifier=None, splash_url=None, pdf_url=None, logs=None,
                 status='published', message=None):
        self.identifier = identifier
        self.splash_url = splash_url
        self.pdf_url = pdf_url
        self.logs = logs
        if status not in [x for x,y in DEPOSIT_STATUS_CHOICES]:
            raise ValueError('invalid status '+unicode(status))
        self.status = status
        self.message = message
        self.oairecord = None
        self.additional_info = []

class RepositoryProtocol(object):
    """
    The protocol for a repository where papers can be deposited.
    Actual implementations should inherit from this class.
    """

    form_class = BaseMetadataForm

    def __init__(self, repository, **kwargs):
        self.repository = repository
        self._logs = None
        self.paper = None
        self.user = None

    def protocol_identifier(self):
        """
        Returns an identifier for the protocol.
        """
        return type(self).__name__

    def init_deposit(self, paper, user):
        """
        Called when a user starts considering depositing a paper to a repository.

        :param paper: The paper to be deposited.
        :param user: The user submitting the deposit.
        :returns: a boolean indicating if the repository can be used in this case.
        """
        self.paper = paper
        self.user = user
        self._logs = ''
        return True

    def get_form_initial_data(self):
        """
        Returns the form's initial values.
        """
        return {'paper_id':self.paper.id}

    def get_form(self):
        """
        Returns the form where the user will be able to give additional metadata.
        It is prefilled with the initial data from `get_form_initial_data`
        """
        return self.form_class(paper=self.paper, initial=self.get_form_initial_data())

    def get_bound_form(self, data):
        """
        Returns a bound version of the form, with the given data.
        Here, data is expected to come from a POST request generated by
        the user, ready for validation.
        """
        return self.form_class(paper=self.paper, data=data)

    def submit_deposit(self, pdf, form, dry_run=False):
        """
        Submit a paper to the repository.
        This is expected to raise DepositError if something goes wrong.

        :param pdf: Filename to the PDF file to submit
        :param form: The form returned by get_form and completed by the user.
        :param dry_run: if True, should
        :returns: a DepositResult object.
        """
        raise NotImplemented(
            'submit_deposit should be implemented in the RepositoryInterface instance.')

    def refresh_deposit_status(self, deposit_record):
        """
        Given the DepositRecord created by a previous deposit,
        update its deposit status. This function will be called
        regularly, so that we can stay in sync with the deposit
        while it makes it way through the pipeline in the repository.

        By default this does not do anything (i.e. leaves the
        DepositRecord unchanged).

        :param deposit_record: the DepositRecord to update
        """
        pass

    def submit_deposit_wrapper(self, *args, **kwargs):
        """
        Wrapper of the submit_deposit method (that should not need to be
        reimplemented). It catches DepositErrors raised in the deposit process
        and adds the logs to its return value.
        """
        # Small hack to get notifications
        name = self.user.name
        if self.user.first_name and self.user.last_name:
            name = '%s %s' % (self.user.first_name,self.user.last_name)
        notification_payload = {
                'name':name,
                'repo':self.repository.name,
                'paperurl':reverse('paper', args=[self.paper.pk]),
            }
        try:
            result = self.submit_deposit(*args, **kwargs)
            result.logs = self._logs

            # Create the corresponding OAI record
            if result.splash_url:
                rec = BareOaiRecord(
                        source=self.repository.oaisource,
                        identifier=('deposition:%d:%s' %
                                    (self.repository.id, unicode(result.identifier))),
                        splash_url=result.splash_url,
                        pdf_url=result.pdf_url)
                result.oairecord = self.paper.add_oairecord(rec)

            settings.DEPOSIT_NOTIFICATION_CALLBACK(notification_payload)

            return result
        except DepositError as e:
            self.log('Message: '+e.args[0])
            notification_payload['paperurl'] += ' '+e.args[0]
            settings.DEPOSIT_NOTIFICATION_CALLBACK(notification_payload)
            return DepositResult(logs=self._logs, status='failed', message=e.args[0])
        except Exception as e:
            self.log("Caught exception:")
            self.log(str(type(e))+': '+str(e)+'')
            self.log(traceback.format_exc())
            return DepositResult(logs=self._logs, status='failed', message=__('Failed to connect to the repository. Please try again later.'))

    def log(self, line):
        """
        Logs a line in the protocol log.
        """
        self._logs += line+'\n'

    def log_request(self, r, expected_status_code, error_msg):
        """
        Logs an HTTP request and raises an error if the status code is unexpected.
        """
        self.log('--- Request to %s\n' % r.url)
        self.log('Status code: %d (expected %d)\n' %
                 (r.status_code, expected_status_code))
        if r.status_code != expected_status_code:
            self.log('Server response:')
            self.log(r.text)
            self.log('')
            raise DepositError(error_msg)
