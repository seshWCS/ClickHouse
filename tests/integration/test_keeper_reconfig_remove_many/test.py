#!/usr/bin/env python3

import pytest
from helpers.cluster import ClickHouseCluster
import helpers.keeper_utils as ku
import os
from kazoo.client import KazooClient, KazooState
from kazoo.exceptions import BadVersionException, BadArgumentsException

cluster = ClickHouseCluster(__file__)
CONFIG_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "configs")

nodes = [
    cluster.add_instance(f"node{i}", main_configs=[f"configs/keeper{i}.xml"])
    for i in range(1, 6)
]
node1, node2, node3, node4, node5 = nodes

log_msg_removed = "has been removed from the cluster"
zk1, zk2, zk3, zk4, zk5 = None, None, None, None, None


@pytest.fixture(scope="module")
def started_cluster():
    try:
        cluster.start()
        yield cluster
    finally:
        for conn in [zk1, zk2, zk3, zk4, zk5]:
            if conn:
                conn.stop()
                conn.close()

        cluster.shutdown()


def get_fake_zk(node):
    return ku.get_fake_zk(cluster, node)


def test_reconfig_remove_2_and_leader(started_cluster):
    """
    Remove 2 followers from a cluster of 5. Remove leader from 3 nodes.
    """

    zk1 = get_fake_zk(node1)
    config = ku.get_config_str(zk1)
    print("Initial config", config)

    assert len(config.split("\n")) == 5

    for i in range(100):
        zk1.create(f"/test_two_{i}", b"somedata")

    zk4 = get_fake_zk(node4)
    zk4.sync("/test_two_0")
    ku.wait_configs_equal(config, zk4)

    zk5 = get_fake_zk(node5)
    zk5.sync("/test_two_0")
    ku.wait_configs_equal(config, zk5)

    for i in range(100):
        assert zk4.exists(f"test_two_{i}") is not None
        assert zk5.exists(f"test_two_{i}") is not None

        zk4.create(f"/test_two_{100 + i}", b"otherdata")

    zk2 = get_fake_zk(node2)
    config, _ = zk2.reconfig(joining=None, leaving="4,5", new_members=None)
    config = config.decode("utf-8")

    print("After removing 4,5", config)
    assert len(config.split("\n")) == 3
    assert "node1" in config
    assert "node2" in config
    assert "node3" in config
    assert "node4" not in config
    assert "node5" not in config

    zk1.stop()
    zk1.close()
    zk1 = get_fake_zk(node1)
    zk1.sync("/test_two_0")

    ku.wait_configs_equal(config, zk1)

    for i in range(200):
        assert zk1.exists(f"test_two_{i}") is not None
        assert zk2.exists(f"test_two_{i}") is not None

    with pytest.raises(Exception):
        zk4.stop()
        zk4.close()
        zk4 = get_fake_zk(node4)
        zk4.sync("/test_two_0")

    with pytest.raises(Exception):
        zk5.stop()
        zk5.close()
        zk5 = get_fake_zk(node5)
        zk5.sync("/test_two_0")

    assert not node1.contains_in_log(log_msg_removed)
    assert not node2.contains_in_log(log_msg_removed)
    assert not node3.contains_in_log(log_msg_removed)
    assert node4.contains_in_log(log_msg_removed)
    assert node5.contains_in_log(log_msg_removed)

    assert ku.is_leader(cluster, node1)

    for i in range(100):
        zk1.create(f"/test_leader_{i}", b"somedata")

    # when a leader gets a remove request, it must yield leadership
    config, _ = zk1.reconfig(joining=None, leaving="1", new_members=None)
    config = config.decode("utf-8")
    print("After removing 1 (leader)", config)

    assert len(config.split("\n")) == 2
    assert "node1" not in config
    assert "node2" in config
    assert "node3" in config
    assert "node4" not in config
    assert "node5" not in config

    zk2.stop()
    zk2.close()
    zk2 = get_fake_zk(node2)
    zk2.sync("/test_leader_0")
    ku.wait_configs_equal(config, zk2)

    zk3 = get_fake_zk(node3)
    zk3.sync("/test_leader_0")
    ku.wait_configs_equal(config, zk3)

    for i in range(100):
        assert zk2.exists(f"test_leader_{i}") is not None
        assert zk3.exists(f"test_leader_{i}") is not None

    with pytest.raises(Exception):
        zk1.stop()
        zk1.close()
        zk1 = get_fake_zk(node1)
        zk1.sync("/test_leader_0")

    assert node1.contains_in_log(log_msg_removed)
    assert not node2.contains_in_log(log_msg_removed)
    assert not node3.contains_in_log(log_msg_removed)
