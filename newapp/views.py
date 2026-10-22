from django.db import transaction
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth.models import User
from .serializers import RegisterSerializer, UserSerializer
from rest_framework import status
from .models import Product, Category, Cart, CartItem, Order, OrderItem
from .serializers import ProductSerializer, CategorySerializer, CartSerializer, CartItemSerializer
@api_view(['GET'])
def get_products(request):
    products = Product.objects.all()
    serializer = ProductSerializer(products, many=True) 
    return Response(serializer.data)

@api_view(['GET'])
def get_product(request, pk):
    try:
        product = Product.objects.get(id=pk)
        serializer = ProductSerializer(product, context = {'request': request})
        return Response(serializer.data)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)

@api_view(['GET'])
def get_categories(request):
    categories = Category.objects.all()
    serializer = CategorySerializer(categories, many=True)
    return Response(serializer.data)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_cart(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    serializer = CartSerializer(cart)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_cart(request):
    product_id = request.data.get('product_id')
    product = Product.objects.get(id=product_id)
    cart, created = Cart.objects.get_or_create(user=request.user)
    item, created = CartItem.objects.get_or_create(cart=cart, product=product)
    if not created:
        item.quantity += 1
        item.save()
    return Response({'message': 'Product added to cart',"cart":CartSerializer(cart).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_cart_quantity(request):
    item_id = request.data.get('item_id')
    quantity = request.data.get('quantity')

    if item_id is None or quantity is None:
        return Response(
            {'error': 'Item ID and quantity are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        item_id = int(item_id)
        quantity = int(quantity)
    except (TypeError, ValueError):
        return Response(
            {'error': 'Item ID and quantity must be integers'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if item_id < 1 or quantity < 1:
        return Response(
            {'error': 'Item ID and quantity must be positive'},
            status=status.HTTP_400_BAD_REQUEST
        )

    
    try:
        item = CartItem.objects.get(
            id=item_id,
            cart__user=request.user
        )
    except CartItem.DoesNotExist:
        return Response(
            {'error': 'Cart item not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    item.quantity = quantity
    item.save(update_fields=['quantity'])

    return Response(CartItemSerializer(item).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remove_from_cart(request):
    item_id = request.data.get('item_id')

    try:
        item_id = int(item_id)
        if item_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        return Response(
            {'error': 'A valid item ID is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    
    deleted_count, _ = CartItem.objects.filter(
        id=item_id,
        cart__user=request.user
    ).delete()

    if deleted_count == 0:
        return Response(
            {'error': 'Cart item not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response({'message': 'Item removed from cart'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    data = request.data

    name = str(data.get('name', '')).strip()
    address = str(data.get('address', '')).strip()
    phone = str(data.get('phone', '')).strip()
    payment_method = str(data.get('payment_method', 'COD')).upper()

    if not name or len(name) > 150:
        return Response(
            {'error': 'Enter a valid customer name (maximum 150 characters).'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not address:
        return Response(
            {'error': 'Delivery address is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not phone.isdigit() or not 10 <= len(phone) <= 15:
        return Response(
            {'error': 'Enter a valid phone number containing 10 to 15 digits.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if payment_method not in ('COD', 'ONLINE'):
        return Response(
            {'error': 'Unsupported payment method.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            cart, _ = Cart.objects.get_or_create(user=request.user)

            
            items = list(
                CartItem.objects
                .select_for_update()
                .filter(cart=cart)
                .select_related('product')
            )

            if not items:
                return Response(
                    {'error': 'Cart is empty.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            total = sum(
                (item.product.price * item.quantity for item in items),
                start=items[0].product.price * 0
            )

            order = Order.objects.create(
                user=request.user,
                customer_name=name,
                shipping_address=address,
                phone=phone,
                payment_method=payment_method,
                total_amount=total
            )

            OrderItem.objects.bulk_create([
                OrderItem(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    price=item.product.price
                )
                for item in items
            ])

            CartItem.objects.filter(
                id__in=[item.id for item in items],
                cart=cart
            ).delete()

        return Response(
            {
                'message': 'Order created successfully.',
                'order_id': order.id,
                'total_amount': str(order.total_amount),
                'status': order.status,
                'payment_method': order.payment_method
            },
            status=status.HTTP_201_CREATED
        )

    except Exception:
        
        import logging
        logging.getLogger(__name__).exception(
            'Order creation failed for user %s', request.user.id
        )
        return Response(
            {'error': 'Unable to create order. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_orders(request):
    orders = (
        Order.objects
        .filter(user=request.user)
        .prefetch_related('items__product')
        .order_by('-created_at')
    )

    result = []

    for order in orders:
        result.append({
            'id': order.id,
            'customer_name': order.customer_name,
            'shipping_address': order.shipping_address,
            'phone': order.phone,
            'payment_method': order.payment_method,
            'payment_method_display': order.get_payment_method_display(),
            'status': order.status,
            'status_display': order.get_status_display(),
            'total_amount': str(order.total_amount),
            'created_at': order.created_at.isoformat(),
            'items': [
                {
                    'product_id': item.product_id,
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'price': str(item.price),
                    'subtotal': str(item.price * item.quantity),
                }
                for item in order.items.all()
            ],
        })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_order_detail(request, order_id):
    try:
        order = (
            Order.objects
            .prefetch_related('items__product')
            .get(id=order_id, user=request.user)
        )
    except Order.DoesNotExist:
        return Response(
            {'error': 'Order not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    result = {
        'id': order.id,
        'customer_name': order.customer_name,
        'shipping_address': order.shipping_address,
        'phone': order.phone,
        'payment_method': order.payment_method,
        'payment_method_display': order.get_payment_method_display(),
        'status': order.status,
        'status_display': order.get_status_display(),
        'total_amount': str(order.total_amount),
        'created_at': order.created_at.isoformat(),
        'items': [
            {
                'product_id': item.product_id,
                'product_name': item.product.name,
                'quantity': item.quantity,
                'price': str(item.price),
                'subtotal': str(item.price * item.quantity),
            }
            for item in order.items.all()
        ],
    }

    return Response(result)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({"message": "User created successfully", "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
  
