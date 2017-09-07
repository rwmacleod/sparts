# Copyright 2016 Intel Corporation
# Copyright 2017 Wind River Systems
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------

import hashlib
import base64
from base64 import b64encode
import time
import requests
import yaml

import sawtooth_signing.secp256k1_signer as signing

from sawtooth_sdk.protobuf.transaction_pb2 import TransactionHeader
from sawtooth_sdk.protobuf.transaction_pb2 import Transaction
from sawtooth_sdk.protobuf.batch_pb2 import BatchList
from sawtooth_sdk.protobuf.batch_pb2 import BatchHeader
from sawtooth_sdk.protobuf.batch_pb2 import Batch

from sawtooth_envelope.envelope_exceptions import EnvelopeException


def _sha512(data):
    return hashlib.sha512(data).hexdigest()


class EnvelopeClient:
    
    def __init__(self, base_url, keyfile):

        self._base_url = base_url
        try:
            with open(keyfile) as fd:
                self._private_key = fd.read().strip()
                fd.close()
        except:
            raise IOError("Failed to read keys.")

        self._public_key = signing.generate_pubkey(self._private_key)
    
    
    def create(self,artifact_id,short_id,artifact_name,artifact_type,artifact_checksum,path,uri,label,openchain, auth_user=None, auth_password=None):
        return self.send_envelope_transaction_request(artifact_id,short_id,artifact_name,artifact_type,artifact_checksum,path,uri,label,openchain,"create","",
                                 auth_user=auth_user,
                                 auth_password=auth_password)
        
        

    def list(self, auth_user=None, auth_password=None):
        envelope_prefix = self._get_prefix()

        result = self._send_request(
            "state?address={}".format(envelope_prefix),
            auth_user=auth_user,
            auth_password=auth_password
        )

        try:
            encoded_entries = yaml.safe_load(result)["data"]

            return [
                base64.b64decode(entry["data"]) for entry in encoded_entries
            ]

        except BaseException:
            return None

    def add_artifact(self,artifact_id,sub_artifact_id):
        return self.send_envelope_transaction_request(artifact_id,"","","","","","","","","AddArtifact",sub_artifact_id)
    
    
    def show(self, artifact_id, auth_user=None, auth_password=None):
        address = self._get_address(artifact_id)

        result = self._send_request("state/{}".format(address), artifact_id=artifact_id,
                                    auth_user=auth_user,
                                    auth_password=auth_password)
        try:
            return base64.b64decode(yaml.safe_load(result)["data"])

        except BaseException:
            return None

    def _get_status(self, batch_id, auth_user=None, auth_password=None):
        try:
            result = self._send_request(
                'batch_status?id={}&wait={}'.format(batch_id),
                auth_user=auth_user,
                auth_password=auth_password)
            return yaml.safe_load(result)['data'][0]['status']
        except BaseException as err:
            raise EnvelopeException(err)
   
    def _get_prefix(self):
        return _sha512('envelope'.encode('utf-8'))[0:6]

    
    def _get_address(self, artifact_id):
        envelope_prefix = self._get_prefix()
        envelope_address = _sha512(artifact_id.encode('utf-8'))[0:64]
        return envelope_prefix + envelope_address

   
    def _send_request(
            self, suffix, data=None,
            content_type=None, name=None, auth_user=None, auth_password=None):
        if self._base_url.startswith("http://"):
            url = "{}/{}".format(self._base_url, suffix)
        else:
            url = "http://{}/{}".format(self._base_url, suffix)

        headers = {}
        if auth_user is not None:
            auth_string = "{}:{}".format(auth_user, auth_password)
            b64_string = b64encode(auth_string.encode()).decode()
            auth_header = 'Basic {}'.format(b64_string)
            headers['Authorization'] = auth_header

        if content_type is not None:
            headers['Content-Type'] = content_type

        try:
            if data is not None:
                result = requests.post(url, headers=headers, data=data)
            else:
                result = requests.get(url, headers=headers)

            if result.status_code == 404:
                raise EnvelopeException("No such envelope: {}".format(name))

            elif not result.ok:
                raise EnvelopeException("Error {}: {}".format(
                    result.status_code, result.reason))

        except BaseException as err:
            raise EnvelopeException(err)

        return result.text

    # Create envelope transaction request 
    def send_envelope_transaction_request(self,artifact_id,short_id="",artifact_name="",artifact_type="",artifact_checksum="",path="",uri="",label="",openchain="", action="", sub_artifact_id="",
                     auth_user=None, auth_password=None):
        # Serialization is just a delimited utf-8 encoded string
        payload = ",".join([artifact_id,str(short_id),str(artifact_name),str(artifact_type),str(artifact_checksum),str(path),str(uri),str(label),str(openchain), action,str(sub_artifact_id)]).encode()

        # Construct the address
        address = self._get_address(artifact_id)

        header = TransactionHeader(
            signer_pubkey=self._public_key,
            family_name="envelope",
            family_version="1.0",
            inputs=[address],
            outputs=[address],
            dependencies=[],
            payload_encoding="csv-utf8",
            payload_sha512=_sha512(payload),
            batcher_pubkey=self._public_key,
            nonce=time.time().hex().encode()
        ).SerializeToString()

        signature = signing.sign(header, self._private_key)

        transaction = Transaction(
            header=header,
            payload=payload,
            header_signature=signature
        )

        batch_list = self._create_batch_list([transaction])
        batch_id = batch_list.batches[0].header_signature

        result = self._send_request(
            "batches", batch_list.SerializeToString(),
            'application/octet-stream', auth_user=auth_user,
                auth_password=auth_password
        )
        
        return result

    # Create Batch List
    def _create_batch_list(self, transactions):
        transaction_signatures = [t.header_signature for t in transactions]

        header = BatchHeader(
            signer_pubkey=self._public_key,
            transaction_ids=transaction_signatures
        ).SerializeToString()

        signature = signing.sign(header, self._private_key)

        batch = Batch(
            header=header,
            transactions=transactions,
            header_signature=signature
        )
        return BatchList(batches=[batch])
