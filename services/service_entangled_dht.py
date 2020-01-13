#!/usr/bin/python
# service_entangled_dht.py
#
# Copyright (C) 2008 Veselin Penev, https://bitdust.io
#
# This file (service_entangled_dht.py) is part of BitDust Software.
#
# BitDust is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BitDust Software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with BitDust Software.  If not, see <http://www.gnu.org/licenses/>.
#
# Please contact us if you have any questions at bitdust.io@gmail.com
#
#
#
#

"""
..

module:: service_entangled_dht
"""

from __future__ import absolute_import
from services.local_service import LocalService


def create_service():
    return EntangledDHTService()


class EntangledDHTService(LocalService):

    service_name = 'service_entangled_dht'
    config_path = 'services/entangled-dht/enabled'

    def dependent_on(self):
        return [
            'service_udp_datagrams',
        ]

    def network_configuration(self):
        import re
        from main import config
        from dht.entangled.kademlia import constants  # @UnresolvedImport
        known_dht_nodes_str = config.conf().getData('services/entangled-dht/known-nodes').strip()
        known_dht_nodes = []
        if known_dht_nodes_str:
            for dht_node_str in re.split('\n|;|,| ', known_dht_nodes_str):
                if dht_node_str.strip():
                    try:
                        dht_node = dht_node_str.strip().split(':')
                        dht_node_host = dht_node[0].strip()
                        dht_node_port = int(dht_node[1].strip())
                    except:
                        continue
                    known_dht_nodes.append({
                        "host": dht_node_host,
                        "udp_port": dht_node_port,
                    })
        if not known_dht_nodes:
            from main import network_config
            default_network_config = network_config.read_network_config_file()
            known_dht_nodes = default_network_config['service_entangled_dht']['known_nodes']
        return {
            "bucket_size": constants.k,
            "default_age": constants.dataExpireSecondsDefaut,
            "max_age": constants.dataExpireTimeout,
            "parallel_calls": constants.alpha,
            "refresh_timeout": constants.refreshTimeout,
            "rpc_timeout": constants.rpcTimeout,
            "known_nodes": known_dht_nodes,
        }

    def start(self):
        from twisted.internet.defer import Deferred
        from logs import lg
        from dht import dht_records
        from dht import dht_service
        from dht import known_nodes
        from main import settings
        from main.config import conf
        conf().addConfigNotifier('services/entangled-dht/udp-port', self._on_udp_port_modified)
        known_seeds = known_nodes.nodes()
        dht_layers = list(dht_records.LAYERS_REGISTRY.keys())
        dht_service.init(
            udp_port=settings.getDHTPort(),
            dht_dir_path=settings.DHTDataDir(),
            open_layers=dht_layers,
        )
        lg.info('DHT known seed nodes are : %r   DHT layers are : %r' % (known_seeds, dht_layers, ))
        self.starting_deferred = Deferred()
        d = dht_service.connect(
            seed_nodes=known_seeds,
            layer_id=0,
            attach=True,
        )
        d.addCallback(self._on_connected)
        d.addErrback(self._on_connect_failed)
        return self.starting_deferred

    def stop(self):
        from dht import dht_records
        from dht import dht_service
        from main.config import conf
        for layer_id in dht_records.LAYERS_REGISTRY.keys():
            dht_service.close_layer(layer_id)
        dht_service.node().remove_rpc_callback('request')
        dht_service.node().remove_rpc_callback('store')
        conf().removeConfigNotifier('services/entangled-dht/udp-port')
        dht_service.disconnect()
        dht_service.shutdown()
        return True

    def health_check(self):
        return True

    def _on_connected(self, ok):
        from twisted.internet.defer import DeferredList
        from logs import lg
        from dht import dht_service
        from dht import known_nodes
        from main.config import conf
        lg.info('DHT node connected  ID0=[%s] : %r' % (dht_service.node().layers[0], ok))
        dht_service.node().add_rpc_callback('store', self._on_dht_rpc_store)
        dht_service.node().add_rpc_callback('request', self._on_dht_rpc_request)
        known_seeds = known_nodes.nodes()
        dl = []
        attached_layers = conf().getData('services/entangled-dht/attached-layers', default='')
        if attached_layers:
            lg.info('more DHT layers to be attached: %r' % attached_layers)
            for layer_id in attached_layers.split(','):
                if layer_id.strip():
                    dl.append(dht_service.connect(
                        seed_nodes=known_seeds,
                        layer_id=int(layer_id.strip()),
                        attach=True,
                    ))
        if dl:
            d = DeferredList(dl)
            d.addCallback(self._on_layers_attached)
            d.addErrback(self._on_connect_failed)
        else:
            if self.starting_deferred:
                self.starting_deferred.callback(True)
                self.starting_deferred = None
        return ok

    def _on_layers_attached(self, ok):
        if self.starting_deferred:
            self.starting_deferred.callback(True)
            self.starting_deferred = None
        return ok

    def _on_connect_failed(self, err):
        from logs import lg
        lg.err('DHT connect failed : %r' % err)
        if self.starting_deferred:
            self.starting_deferred.errback(err)
            self.starting_deferred = None
        return err

    def _on_udp_port_modified(self, path, value, oldvalue, result):
        from p2p import network_connector
        from logs import lg
        lg.info('DHT udp port modified %s->%s : %s' % (oldvalue, value, path))
        if network_connector.A():
            network_connector.A('reconnect')

    def _on_dht_rpc_store(self, key, value, originalPublisherID, age, expireSeconds, **kwargs):
        from dht import dht_service
        return dht_service.validate_before_store(key, value, originalPublisherID, age, expireSeconds, **kwargs)
    
    def _on_dht_rpc_request(self, key, **kwargs):
        from dht import dht_service
        return dht_service.validate_before_request(key, **kwargs)
