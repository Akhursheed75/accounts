from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import accessible_shop_ids, get_current_user, require
from app.core.errors import Conflict, NotFound
from app.db.session import get_db
from app.models import City, Shop, User
from app.schemas.common import Message
from app.schemas.org import CityIn, CityOut, ShopIn, ShopOut, ShopUpdate
from app.services import audit

router = APIRouter(tags=["shops"])


def _out(shop: Shop) -> ShopOut:
    return ShopOut(
        id=shop.id, code=shop.code, name=shop.name, city_id=shop.city_id,
        city_name=shop.city.name if shop.city else None,
        is_active=shop.is_active, is_demo=shop.is_demo,
    )


@router.get("/shops", response_model=list[ShopOut])
def list_shops(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.read")),
) -> list[ShopOut]:
    stmt = select(Shop).order_by(Shop.code)
    allowed = accessible_shop_ids(user)
    if allowed is not None:
        stmt = stmt.where(Shop.id.in_(allowed or [-1]))
    if not include_inactive:
        stmt = stmt.where(Shop.is_active.is_(True))
    return [_out(s) for s in db.scalars(stmt)]


@router.post("/shops", response_model=ShopOut, status_code=201)
def create_shop(
    payload: ShopIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.manage")),
) -> ShopOut:
    if db.scalar(select(Shop).where(Shop.code == payload.code)):
        raise Conflict(f"A shop with the code '{payload.code}' already exists.")
    if payload.city_id and not db.get(City, payload.city_id):
        raise NotFound("That city does not exist.")
    shop = Shop(**payload.model_dump())
    db.add(shop)
    db.flush()
    audit.record(db, action=audit.Actions.CREATE_SHOP, module="shops", user=user,
                 record_type="shop", record_id=shop.id,
                 summary=f"Created shop {shop.code} — {shop.name}",
                 new_values=payload.model_dump())
    db.commit()
    db.refresh(shop)
    return _out(shop)


@router.patch("/shops/{shop_id}", response_model=ShopOut)
def update_shop(
    shop_id: int,
    payload: ShopUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.manage")),
) -> ShopOut:
    shop = db.get(Shop, shop_id)
    if not shop:
        raise NotFound("That shop does not exist.")
    before = {"code": shop.code, "name": shop.name, "city_id": shop.city_id,
              "is_active": shop.is_active}
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != shop.code:
        if db.scalar(select(Shop).where(Shop.code == changes["code"])):
            raise Conflict(f"A shop with the code '{changes['code']}' already exists.")
    for key, value in changes.items():
        setattr(shop, key, value)
    after = {"code": shop.code, "name": shop.name, "city_id": shop.city_id,
             "is_active": shop.is_active}
    old, new = audit.diff(before, after)
    audit.record(db, action=audit.Actions.EDIT_SHOP, module="shops", user=user,
                 record_type="shop", record_id=shop.id,
                 summary=f"Edited shop {shop.code}", old_values=old, new_values=new)
    db.commit()
    db.refresh(shop)
    return _out(shop)


@router.get("/cities", response_model=list[CityOut])
def list_cities(
    db: Session = Depends(get_db), user: User = Depends(require("shop.read"))
) -> list[CityOut]:
    return list(db.scalars(select(City).order_by(City.name)))


@router.post("/cities", response_model=CityOut, status_code=201)
def create_city(
    payload: CityIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.manage")),
) -> CityOut:
    if db.scalar(select(City).where(City.name == payload.name)):
        raise Conflict(f"The city '{payload.name}' already exists.")
    city = City(**payload.model_dump())
    db.add(city)
    db.flush()
    audit.record(db, action=audit.Actions.CREATE_SHOP, module="shops", user=user,
                 record_type="city", record_id=city.id, summary=f"Created city {city.name}")
    db.commit()
    db.refresh(city)
    return city


@router.delete("/cities/{city_id}", response_model=Message)
def delete_city(
    city_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.manage")),
) -> Message:
    city = db.get(City, city_id)
    if not city:
        raise NotFound("That city does not exist.")
    if db.scalar(select(Shop).where(Shop.city_id == city_id)):
        raise Conflict("Shops are still assigned to this city.")
    db.delete(city)
    audit.record(db, action=audit.Actions.EDIT_SHOP, module="shops", user=user,
                 record_type="city", record_id=city_id, summary=f"Deleted city {city.name}")
    db.commit()
    return Message(message="City deleted.")
