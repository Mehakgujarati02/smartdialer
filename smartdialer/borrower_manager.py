import threading

from smartdialer.models import Borrower, BorrowerStatus


class BorrowerManager:

    def __init__(self):
        self.borrowers = {}
        self.lock = threading.Lock()

    def add_borrower(self, borrower: Borrower):
        with self.lock:
            self.borrowers[borrower.id] = borrower

    def get_waiting_borrowers(self):
        with self.lock:
            return [
                borrower
                for borrower in self.borrowers.values()
                if borrower.status == BorrowerStatus.WAITING
            ]

    def reserve_borrower(self):
        with self.lock:

            waiting_borrowers = [
                borrower
                for borrower in self.borrowers.values()
                if borrower.status == BorrowerStatus.WAITING
            ]

            if not waiting_borrowers:
                return None

            # Higher priority borrower gets selected first
            waiting_borrowers.sort(
                key=lambda borrower: borrower.priority,
                reverse=True
            )

            borrower = waiting_borrowers[0]
            borrower.status = BorrowerStatus.RESERVED

            return borrower

    def release_borrower(self, borrower_id):
        with self.lock:
            borrower = self.borrowers.get(borrower_id)

            if borrower is None:
                return False

            borrower.status = BorrowerStatus.WAITING
            return True

    def complete_borrower(self, borrower_id):
        with self.lock:
            borrower = self.borrowers.get(borrower_id)

            if borrower is None:
                return False

            borrower.status = BorrowerStatus.COMPLETED
            return True

    def mark_borrower_failed(self, borrower_id):
        """
        Terminal disposition, distinct from release_borrower() (which
        puts the borrower back in the WAITING pool for an immediate
        retry). Used for outcomes where re-dialing right away would
        repeat the same problem -- most notably an abandoned call: a
        borrower who already picked up once with no agent available
        should not be silently redialed a moment later.
        """
        with self.lock:
            borrower = self.borrowers.get(borrower_id)

            if borrower is None:
                return False

            borrower.status = BorrowerStatus.FAILED
            return True