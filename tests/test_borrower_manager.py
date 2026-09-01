from smartdialer.borrower_manager import BorrowerManager
from smartdialer.models import Borrower, BorrowerStatus


def test_borrower_can_be_added():

    manager = BorrowerManager()

    borrower = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="9999999999"
    )

    manager.add_borrower(borrower)

    assert len(manager.borrowers) == 1


def test_highest_priority_borrower_is_reserved_first():

    manager = BorrowerManager()

    borrower1 = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="1111111111",
        priority=5
    )

    borrower2 = Borrower(
        id="B2",
        name="Borrower 2",
        phone_number="2222222222",
        priority=10
    )

    manager.add_borrower(borrower1)
    manager.add_borrower(borrower2)

    reserved = manager.reserve_borrower()

    assert reserved.id == "B2"
    assert reserved.status == BorrowerStatus.RESERVED


def test_no_waiting_borrower_returns_none():

    manager = BorrowerManager()

    borrower = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="9999999999",
        status=BorrowerStatus.COMPLETED
    )

    manager.add_borrower(borrower)

    reserved = manager.reserve_borrower()

    assert reserved is None