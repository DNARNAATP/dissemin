#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
from __future__ import unicode_literals

import json

import requests

from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from deposit.osf.forms import OSFForm
from django.utils.translation import ugettext as __
from papers.utils import kill_html


class OSFProtocol(RepositoryProtocol):
    """
    A protocol to submit using the OSF REST API.
    """
    form_class = OSFForm

    def __init__(self, repository, **kwargs):
        super(OSFProtocol, self).__init__(repository, **kwargs)
        # We let the interface define another API endpoint (sandbox…).
        self.api_url = repository.endpoint

        if self.api_url == "https://test-api.osf.io/":
            self.no_license_id = "58fd62fcda3e2400012ca5cc"
        else:
            self.no_license_id = "563c1cf88c5e4a3877f9e965"

    def init_deposit(self, paper, user):
        """
        Refuse deposit when the paper is already on OSF.
        """
        super(OSFProtocol, self).init_deposit(paper, user)
        return (True)

    def get_form_initial_data(self):
        data = super(OSFProtocol, self).get_form_initial_data()

        if self.paper.abstract:
            data['abstract'] = kill_html(self.paper.abstract)

        return data

    # Get some basic data needed in different methods.
    def get_primary_data(self, form):
        paper = self.paper.json()

        abstract = form.cleaned_data['abstract']

        return (paper, abstract)

    def create_tags(self, form):
        tags = list(form.cleaned_data['tags'].split(','))
        tags = [item.strip() for item in tags]
        tags = [item for item in tags if item != ""]

        return tags

    # Look for a specific subkey.
    def get_key_data(self, key, records):
        for item in records:
            if item.get(key):
                return (item[key])

        return None

    # ---------------------------------------------
    # HERE AFTER GO THE DIFFERENT METHODS
    # NEEDED BY submit_deposit()
    # ---------------------------------------------

    # Get a dictionary containing the first and last names
    # of the authors of a Dissemin paper,
    # ready to be implemented in an OSF Preprints data dict.
    def translate_author(self, dissemin_authors, goal="optional"):
        author = "{} {}".format(dissemin_authors['name']['first'],
                                dissemin_authors['name']['last'])

        if goal == "contrib":
            structure = {
                "data": {
                    "type": "contributors",
                    "attributes": {
                        "full_name": author
                    }
                }
            }
            return structure

        else:
            return author

    # Extract the OSF storage link.
    def translate_links(self, node_links):
        upload_link = node_links['links']['upload']
        return upload_link

    # Send the min. structure.
    # The response should contain the node ID.
    def create_node(self, abstract, tags, authors):
        abstract = abstract
        tags = tags
        authors = authors

        # Required to create a new node.
        # The project will then host the Preprint.
        min_node_structure = {
            "data": {
                "type": "nodes",
                "attributes": {
                    "title": self.paper.title,
                    "category": "project",
                    "description": abstract,
                    "tags": tags
                }
            }
        }

        self.log("### Creating the metadata")
        self.log(json.dumps(min_node_structure, indent=4)+'')
        self.log(json.dumps(authors, indent=4)+'')
        request_url = self.api_url + "v2/nodes/"

        osf_response = requests.post(request_url,
                                     data=json.dumps(min_node_structure),
                                     headers=self.headers)
        self.log_request(osf_response, 201,
                         __('Unable to create a project on OSF.'))

        osf_response = osf_response.json()
        self.node_id = osf_response['data']['id']

    # Get OSF Storage link to later upload
    # the Preprint PDF file.
    def get_newnode_osf_storage(self, node_id):
        self.storage_url = (
            self.api_url + "v2/nodes/{}/files/".format(self.node_id)
        )
        osf_storage_data = requests.get(self.storage_url,
                                        headers=self.headers)
        self.log_request(osf_storage_data, 200,
                         __('Unable to authenticate to OSF.'))

        osf_storage_data = osf_storage_data.json()
        return osf_storage_data

    def add_contributors(self, authors):
        contrib_url = (
            self.api_url + "v2/nodes/" +
            self.node_id + "/contributors/"
        )

        for author in authors:
            contrib = self.translate_author(author, "contrib")
            contrib_response = requests.post(contrib_url,
                                             data=json.dumps(contrib),
                                             headers=self.headers)
            self.log_request(contrib_response, 201,
                             __('Unable to add contributors.'))

    def create_license(self, authors):
        node_url = self.api_url + "v2/nodes/" + self.node_id + "/"
        license_url = self.api_url + "v2/licenses/"
        license_url += (self.license_id + "/")
        authors_list = [self.translate_author(author)
                        for author in authors]

        license_structure = {
                "data": {
                    "type": "nodes",
                    "id": self.node_id,
                    "attributes": {},
                    "relationships": {
                        "license": {
                            "data": {
                                "type": "licenses",
                                "id": self.license_id
                            }
                        }
                    }
                }
            }

        if self.license_id == self.no_license_id:
            license_structure['data']['attributes'] = {
                "node_license": {
                    "year": self.pub_date,
                    "copyright_holders": authors_list
                }
            }
        else:
            license_structure['data']['attributes'] = {
                "node_license": {}
            }

        license_req = requests.patch(node_url,
                                     data=json.dumps(license_structure),
                                     headers=self.headers)
        self.log_request(license_req, 200,
                         __('Unable to update license.'))

        self.log("### Updating License")
        self.log(str(license_req.status_code))
        self.log(license_req.text)
        self.log("==========")
        self.log("self.license_id: {}  | ".format(self.license_id) +
                 "self.no_license_id: {}".format(self.no_license_id))
        self.log("==========")

    def create_preprint(self, pf_path, records):
        preprint_node_url = self.api_url + "v2/preprints/"
        records = records
        paper_doi = self.get_key_data('doi', records)
        pf_path = pf_path

        # -----------------------------------------------
        # The following structure will be used
        # to send a Preprint on OSF once the project
        # has been created there.
        # -----------------------------------------------
        min_preprint_structure = {
            "data": {
                "attributes": {
                    "doi": paper_doi
                },
                "relationships": {
                    "node": {
                        "data": {
                            "type": "nodes",
                            "id": self.node_id
                        }
                    },
                    "primary_file": {
                        "data": {
                            "type": "primary_files",
                            "id": pf_path
                        }
                    },
                    "provider": {
                        "data": {
                            "type": "providers",
                            "id": "osf"
                        }
                    }
                }
            }
        }

        self.log("### Creating Preprint")
        osf_response = requests.post(preprint_node_url,
                                     data=json.dumps(min_preprint_structure),
                                     headers=self.headers)
        self.log_request(osf_response, 201,
                         __('Unable to create the preprint.'))

        self.log(str(osf_response.status_code))

        osf_preprint_response = osf_response.json()

        return osf_preprint_response

    def update_preprint_license(self, authors, preprint_id):
        authors_list = [self.translate_author(author)
                        for author in authors]

        preprint_node_url = (
            self.api_url + "v2/preprints/{}/".format(preprint_id)
        )

        updated_preprint_struc = {
            "data": {
                "type": "nodes",
                "id": preprint_id,
                "attributes": {},
                "relationships": {
                    "license": {
                        "data": {
                            "type": "licenses",
                            "id": self.license_id
                        }
                    }
                }
            }
        }

        if self.license_id == self.no_license_id:
            updated_preprint_struc['data']['attributes'] = {
                "license_record": {
                    "year": self.pub_date,
                    "copyright_holders": authors_list
                }
            }
        else:
            updated_preprint_struc['data']['attributes'] = {
                "license_record": {}
            }

        self.log("### Updating the Preprint License")
        license_req = requests.patch(preprint_node_url,
                                     data=json.dumps(updated_preprint_struc),
                                     headers=self.headers)
        self.log_request(license_req, 200,
                         __('Unable to update the Preprint License.'))

        self.log(str(license_req.status_code))
        self.log(license_req.text)

    # MAIN METHOD
    def submit_deposit(self, pdf, form, dry_run=False):
        if not self.api_url:
            raise DepositError(__("No Repository endpoint provided."))

        if self.repository.api_key is None:
            raise DepositError(__("No OSF token provided."))

        api_key = self.repository.api_key
        self.license_id = form.cleaned_data['license']

        paper, abstract = self.get_primary_data(form)
        authors = paper['authors']
        records = paper['records']
        self.pub_date = paper['date'][:-6]
        tags = self.create_tags(form)

        deposit_result = DepositResult()

        # To connect to the API.
        self.headers = {
            'Authorization': 'Bearer %s' % api_key,
            'Content-Type': 'application/vnd.api+json'
        }

        # Creating the metadata.
        self.create_node(abstract, tags, authors)

        self.log("### Creating a new depository")
        osf_storage_data = self.get_newnode_osf_storage(self.node_id)
        osf_links = osf_storage_data['data']
        osf_upload_link = str(
            list({self.translate_links(entry) for entry in osf_links})
        )
        osf_upload_link = osf_upload_link.replace("[u'", '').replace("']", '')

        self.log("### Uploading the PDF")
        upload_url_suffix = "?kind=file&name=article.pdf"
        upload_url = osf_upload_link + upload_url_suffix
        data = open(pdf, 'r')
        primary_file_data = requests.put(upload_url,
                                         data=data,
                                         headers=self.headers)
        self.log_request(primary_file_data, 201,
                         __('Unable to upload the PDF file.'))
        primary_file_data = primary_file_data.json()

        pf_path = primary_file_data['data']['attributes']['path'][1:]

        self.add_contributors(authors)

        self.create_license(authors)

        # Create the Preprint.
        osf_preprint_response = self.create_preprint(pf_path, records)
        preprint_id = osf_preprint_response['data']['id']

        if self.api_url == "https://test-api.osf.io/":
            preprint_public_url = "https://test.osf.io/" + preprint_id
        else:
            preprint_public_url = "https://osf.io" + preprint_id

        preprint_public_pdf = preprint_public_url + "/download"

        self.update_preprint_license(authors, preprint_id)

        if self.api_url == "https://test-api.osf.io/":
            project_public_url = "https://test.osf.io/" + self.node_id
        else:
            project_public_url = "https://osf.io/" + self.node_id

        self.log("### FINAL DEBUG")
        self.log(project_public_url)
        self.log(preprint_public_url)
        self.log(preprint_public_pdf)

        # deposit_result.identifier = projet_public_url
        # deposit_result.splash_url = preprint_public_url
        # deposit_result.pdf_url = preprint_public_pdf

        return (deposit_result)

protocol_registry.register(OSFProtocol)
