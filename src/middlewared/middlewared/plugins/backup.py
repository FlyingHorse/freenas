from collections import defaultdict
from datetime import datetime
from middlewared.schema import accepts, Int
from middlewared.service import CRUDService, Service, private

import boto3
import enum
import hashlib
import os
import socket
import subprocess


class ReplicationActionType(enum.Enum):
    SEND_STREAM = 1
    DELETE_SNAPSHOTS = 2
    CLEAR_SNAPSHOTS = 3
    DELETE_DATASET = 4


class ReplicationAction(object):
    def __init__(self, type, localfs, remotefs, **kwargs):
        self.type = type
        self.localfs = localfs
        self.remotefs = remotefs
        for k, v in kwargs.items():
            setattr(self, k, v)


class BackupService(CRUDService):

    @private
    def calculate_delta(self, datasets, remoteds, local_snapshots, snapshots_list, recursive=False, followdelete=False):
        remote_datasets = list(filter(lambda s: '@' not in s['name'], snapshots_list))
        actions = []

        def matches(src, tgt):
            return src['snapshot_name'] == tgt['snapshot_name'] and src['created_at'] == tgt['created_at']

        def match_snapshots(local, remote):
            for i in local:
                match = list(filter(lambda s: matches(i, s), remote))
                yield match[0] if match else None

        def convert_snapshot(snap):
            return {
                'name': snap['name'],
                'snapshot_name': snap['snapshot_name'],
                'created_at': snap['properties']['creation']['parsed'],
                'txg': int(snap['properties']['createtxg']['rawvalue']),
                'uuid': snap['properties']['org.freenas:uuid'],
            }

        def extend_with_snapshot_name(snap):
            snap['snapshot_name'] = snap['name'].split('@')[-1] if '@' in snap['name'] else None

        for i in snapshots_list:
            extend_with_snapshot_name(i)

        for ds in datasets:
            localfs = ds
            # Remote fs is always the same as local fs for BACKUP
            #remotefs = localfs.replace(localds, remoteds, 1)
            remotefs = localfs

            """
            local_snapshots = sorted(
                list(map(
                    convert_snapshot,
                    self.dispatcher.call_sync('zfs.dataset.get_snapshots', localfs)
                )),
                key=lambda x: x['txg']
            )

            remote_snapshots = q.query(
                snapshots_list,
                ('name', '~', '^{0}@'.format(remotefs))
            )
            """
            remote_snapshots = snapshots_list

            snapshots = local_snapshots[localfs][:]
            found = None

            if remote_snapshots:
                # Find out the last common snapshot.
                pairs = list(match_snapshots(local_snapshots, remote_snapshots))
                if pairs:
                    pairs.sort(key=lambda p: p[0]['created_at'], reverse=True)
                    match = list(filter(None, pairs))
                    found = match[0][0] if match else None

                if found:
                    if followdelete:
                        delete = []
                        for snap in remote_snapshots:
                            rsnap = snap['snapshot_name']
                            match = list(filter(lambda s: s['snapshot_name'] == rsnap, local_snapshots))
                            if not match:
                                delete.append(rsnap)

                        if delete:
                            actions.append(ReplicationAction(
                                ReplicationActionType.DELETE_SNAPSHOTS,
                                localfs,
                                remotefs,
                                snapshots=delete
                            ))

                    index = local_snapshots.index(found)

                    for idx in range(index + 1, len(local_snapshots)):
                        actions.append(ReplicationAction(
                            ReplicationActionType.SEND_STREAM,
                            localfs,
                            remotefs,
                            incremental=True,
                            anchor=local_snapshots[idx - 1]['snapshot_name'],
                            snapshot=local_snapshots[idx]['snapshot_name']
                        ))
                else:
                    actions.append(ReplicationAction(
                        ReplicationActionType.CLEAR_SNAPSHOTS,
                        localfs,
                        remotefs,
                        snapshots=[snap['snapshot_name'] for snap in remote_snapshots]
                    ))

                    for idx in range(0, len(snapshots)):
                        actions.append(ReplicationAction(
                            ReplicationActionType.SEND_STREAM,
                            localfs,
                            remotefs,
                            incremental=idx > 0,
                            anchor=snapshots[idx - 1]['snapshot_name'] if idx > 0 else None,
                            snapshot=snapshots[idx]['snapshot_name']
                        ))
            else:
                for idx in range(0, len(snapshots)):
                    actions.append(ReplicationAction(
                        ReplicationActionType.SEND_STREAM,
                        localfs,
                        remotefs,
                        incremental=idx > 0,
                        anchor=snapshots[idx - 1]['snapshot_name'] if idx > 0 else None,
                        snapshot=snapshots[idx]['snapshot_name']
                    ))

        for rds in remote_datasets:
            remotefs = rds
            # Local fs is always the same as remote fs for BACKUP
            localfs = remotefs

            if localfs not in datasets:
                actions.append(ReplicationAction(
                    ReplicationActionType.DELETE_DATASET,
                    localfs,
                    remotefs
                ))

		"""
        total_send_size = 0
        for action in actions:
            if action.type == ReplicationActionType.SEND_STREAM:
                logger.warning('localfs={0}, snapshot={1}, anchor={2}'.format(action.localfs, action.snapshot, getattr(action, 'anchor', None)))
                size = self.dispatcher.call_sync(
                    'zfs.dataset.estimate_send_size',
                    action.localfs,
                    action.snapshot,
                    getattr(action, 'anchor', None)
                )

                action.send_size = size
                total_send_size += size
        """
        return actions

    @private
    def generate_manifest(self, local_snapshots, backup, previous_manifest, actions):
        def make_snapshot_entry(action):
            snapname = '{0}@{1}'.format(action['localfs'], action['snapshot'])
            filename = hashlib.md5(snapname.encode('utf-8')).hexdigest()
            snap = local_snapshots[snapname]

            txg = snap['properties']['createtxg']['rawvalue']
            return {
                'name': snapname,
                'anchor': action.get('anchor'),
                'incremental': action['incremental'],
                'created_at': datetime.fromtimestamp(int(snap['properties']['creation']['rawvalue'])),
                'uuid': snap['properties']['org.freenas:uuid']['value'],
                'txg': int(txg) if txg else None,
                'filename': filename
            }

        snaps = previous_manifest['snapshots'][:] if previous_manifest else []
        new_snaps = []

        for a in actions:
            if a.type == 'SEND_STREAM':
                snap = make_snapshot_entry(a)
                snaps.append(snap)
                new_snaps.append(snap)

        manifest = {
            'hostname': socket.gethostname(),
            'dataset': backup['filesystem'],
            'snapshots': snaps
        }

        return manifest, new_snaps

    def sync(self, id):

        backup = self.middleware.call('datastore.query', 'storage.cloudreplication', [('id', '=', id)], {'get': True})
        if not backup:
            raise ValueError("Unknown id")

        tasks = self.middleware.call('datastore.query', 'storage.task', [('task_filesystem', '=', backup['filesystem'])])
        if not tasks:
            raise ValueError("No periodic snapshot tasks found")

        recursive = False
        for task in tasks:
            if task['task_recursive']:
                recursive = True
                break

        # TODO: Get manifest and find snapshots there
        remote_snapshots = []

        # Calculate delta between remote and local
        proc = subprocess.Popen([
            '/sbin/zfs', 'list',
            '-o', 'name',
            '-H',
        ] + (['-r'] if recursive else []) + [backup['filesystem']],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        datasets = proc.communicate()[0].strip().split('\n')
        assert proc.returncode == 0

        # Snapshots indexed by dataset
        local_snapshots_dataset = defaultdict(list)
        # Snapshots indexed by name
        local_snapshots_ids = {}
        for snapshot in self.middleware.call('zfs.snapshot.query'):
            local_snapshots_dataset[snapshot['dataset']].append(snapshot)
            local_snapshots_ids[snapshot['name']] = snapshot

        for dataset, snapshots in local_snapshots_dataset.iteritems():
            snapshots.sort(key=lambda x: x['properties']['createtxg']['rawvalue'])

        actions = self.calculate_delta(datasets, backup['filesystem'], local_snapshots_dataset, remote_snapshots, followdelete=False)

        manifest = None  #TODO: get previous manifest
        new_manifest, snaps = self.generate_manifest(local_snapshots_ids, backup, manifest, actions)

        # Send new snapshots to remote
        for action in actions:
            read_fd, write_fd = os.pipe()
            if os.fork() == 0:
                os.dup2(write_fd, 1)
                try:
                    for i in os.listdir('/dev/fd'):
                        if i != '1':
                            os.close(int(i))
                except OSError:
                    pass
                os.execv('/sbin/zfs', ['/sbin/zfs', 'send', '-V', '-p'] + (['-i', snapshot_from] if snapshot_from else []) + [snapshot_to])

            else:
                os.close(write_fd)
                while True:
                    read = os.read(read_fd, 1024 * 1024)
                    if read == b'':
                        break


class BackupS3Service(Service):

    class Config:
        namespace = 'backup.s3'

    @accepts(Int('id'))
    def get_buckets(self, id):
        """Returns buckets from a given S3 credential."""
        credential = self.middleware.call('datastore.query', 'system.cloudcredentials', [('id', '=', id)], {'get': True})

        s3 = boto3.client(
            's3',
            aws_access_key_id=credential['attributes'].get('access_key'),
            aws_secret_access_key=credential['attributes'].get('secret_key'),
        )

        buckets = []
        for bucket in s3.list_buckets()['Buckets']:
            buckets.append({
                'name': bucket['Name'],
                'creation_date': bucket['CreationDate'],
            })

        return buckets
