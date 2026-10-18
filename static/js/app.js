const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})
const framePrices = { '6x8': 899, '8x10': 1199, '12x16': 1499, '16x20': 1999 }
const productData = {
  everyday: { name: 'The Everyday', price: 899 },
  gallery: { name: 'The Gallery', price: 1199 },
  heritage: { name: 'The Heritage', price: 1499 },
  'brass-edit': { name: 'The Brass Edit', price: 1699 },
}
let cart = []
let selectedColor = 'walnut'
let selectedPhoto = null

// Add these variables for the collage customizer
let selectedLayout = '1-single'
let selectedPhotos = [null]
let activePhotoSlot = 0

let publicConfig = { online_payments: false }
let currentUser = null

const $ = (selector) => document.querySelector(selector)
const $$ = (selector) => [...document.querySelectorAll(selector)]
const formatPrice = (value) => currency.format(value)

async function parseJsonResponse(response) {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch (error) {
    const cleanText = text
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    throw new Error(cleanText || 'The server returned an invalid response.')
  }
}

function setModal(element, open) {
  element.classList.toggle('open', open)
  document.body.classList.toggle(
    'modal-open',
    !!document.querySelector('.modal.open'),
  )
}

function cartTotal() {
  return cart.reduce((sum, item) => sum + item.price * item.quantity, 0)
}

function renderCart() {
  const container = $('#cartItems')
  const count = cart.reduce((sum, item) => sum + item.quantity, 0)
  $('#cartCount').textContent = count
  $('#cartCount').dataset.empty = count === 0
  $('#cartTotal').textContent = formatPrice(cartTotal())
  $('#checkoutButton').disabled = !cart.length
  if (!cart.length) {
    container.innerHTML =
      '<p class="empty-cart">Your bag is waiting for a memory.</p>'
    return
  }
  container.innerHTML = cart
    .map(
      (item, index) => `
    <div class="cart-row"><div class="cart-thumb">${item.preview ? `<img src="${item.preview}" alt="Custom frame preview">` : item.name}</div>
    <div class="cart-row-info"><h3>${item.name}</h3><p>${item.type === 'custom' ? `${item.size.replace('x', ' × ')} in · ${item.color}` : 'Ready-to-style frame'}</p><button class="remove-item" data-remove="${index}">Remove</button></div><div class="cart-row-price">${formatPrice(item.price * item.quantity)}</div></div>`,
    )
    .join('')
  $$('[data-remove]').forEach((button) =>
    button.addEventListener('click', () => {
      cart.splice(Number(button.dataset.remove), 1)
      renderCart()
    }),
  )
}

function openCart() {
  $('#cartDrawer').classList.add('open')
  $('#drawerBackdrop').classList.add('open')
  $('#cartDrawer').setAttribute('aria-hidden', 'false')
}
function closeCart() {
  $('#cartDrawer').classList.remove('open')
  $('#drawerBackdrop').classList.remove('open')
  $('#cartDrawer').setAttribute('aria-hidden', 'true')
}
function addToCart(item) {
  cart.push({ ...item, quantity: 1 })
  renderCart()
  openCart()
}

const layoutOptions = [
  { id: '1-single', count: 1, label: 'Single photo', group: '1 photo' },
  { id: '2-side', count: 2, label: 'Side by side', group: '2 photos' },
  { id: '2-vertical', count: 2, label: 'Stacked', group: '2 photos' },
  { id: '2-diagonal', count: 2, label: 'Diagonal', group: '2 photos' },
  { id: '3-feature', count: 3, label: '1 + 2', group: '3 photos' },
  { id: '3-horizontal', count: 3, label: 'Triple row', group: '3 photos' },
  { id: '3-vertical', count: 3, label: 'Triple stack', group: '3 photos' },
  { id: '4-grid', count: 4, label: '2 × 2 grid', group: '4 photos' },
  { id: '4-feature', count: 4, label: '1 + 3', group: '4 photos' },
  { id: '4-portrait', count: 4, label: 'Balanced', group: '4 photos' },
  { id: '5-grid', count: 5, label: 'Balanced 5', group: '5 photos' },
  { id: '5-feature', count: 5, label: '1 + 4', group: '5 photos' },
  { id: '6-grid', count: 6, label: '2 × 3 grid', group: '6 photos' },
  { id: '6-landscape', count: 6, label: 'Wide grid', group: '6 photos' },
  { id: '6-creative', count: 6, label: 'Creative grid', group: '6 photos' },
]

function updateCustomPrice() {
  $('#customTotal').textContent = formatPrice(framePrices[$('#size').value])
}

function selectedLayoutData() {
  return (
    layoutOptions.find((layout) => layout.id === selectedLayout) ||
    layoutOptions[0]
  )
}

function renderLayoutOptions() {
  const groups = [...new Set(layoutOptions.map((layout) => layout.group))]

  $('#layoutSection').innerHTML = groups
    .map(
      (group) => `
    <div class="layout-group">
      <span class="layout-group-title">${group}</span>
      <div class="layout-options">
        ${layoutOptions
          .filter((layout) => layout.group === group)
          .map(
            (layout) => `
          <button
            type="button"
            class="layout-option ${layout.id === selectedLayout ? 'active' : ''}"
            data-layout="${layout.id}"
            aria-label="${layout.label}"
          >
            <span class="layout-mini layout-mini-${layout.id}"></span>
            <span>${layout.label}</span>
          </button>
        `,
          )
          .join('')}
      </div>
    </div>
  `,
    )
    .join('')

  $$('.layout-option').forEach((button) => {
    button.addEventListener('click', () => {
      selectedLayout = button.dataset.layout
      const layout = selectedLayoutData()

      selectedPhotos = selectedPhotos.slice(0, layout.count)
      while (selectedPhotos.length < layout.count) selectedPhotos.push(null)

      renderLayoutOptions()
      renderPhotoSlots()
      renderCollagePreview()
    })
  })
}

function renderPhotoSlots() {
  const layout = selectedLayoutData()

  $('#photoCountLabel').textContent =
    `${layout.count} ${layout.count === 1 ? 'photo' : 'photos'}`

  $('#photoSlots').innerHTML = selectedPhotos
    .map(
      (file, index) => `
    <div class="photo-slot ${file ? 'has-photo' : ''}">
      <button type="button" class="photo-slot-main" data-photo-slot="${index}">
        ${
          file
            ? `<img src="${URL.createObjectURL(file)}" alt="Photo ${index + 1}"><span>Replace</span>`
            : `<span class="photo-slot-plus">+</span><span>Add photo ${index + 1}</span>`
        }
      </button>
      ${file ? `<button type="button" class="photo-slot-remove" data-photo-remove="${index}" aria-label="Remove photo ${index + 1}">×</button>` : ''}
    </div>
  `,
    )
    .join('')

  $$('[data-photo-slot]').forEach((button) => {
    button.addEventListener('click', () => {
      activePhotoSlot = Number(button.dataset.photoSlot)
      $('#photoUpload').value = ''
      $('#photoUpload').click()
    })
  })

  $$('[data-photo-remove]').forEach((button) => {
    button.addEventListener('click', () => {
      selectedPhotos[Number(button.dataset.photoRemove)] = null
      renderPhotoSlots()
      renderCollagePreview()
    })
  })
}

function renderCollagePreview() {
  const layout = selectedLayoutData()
  const frame = $('#previewFrame')
  const grid = $('#collagePreviewGrid')

  frame.className = `custom-preview-frame collage-layout layout-${selectedLayout}`
  grid.innerHTML = selectedPhotos
    .map((file, index) => {
      if (!file) {
        return `<div class="collage-slot-empty">${index + 1}</div>`
      }

      return `<div class="collage-preview-photo">
      <img src="${URL.createObjectURL(file)}" alt="Collage photo ${index + 1}">
    </div>`
    })
    .join('')

  $('#previewPlaceholder').style.display = selectedPhotos.some(Boolean)
    ? 'none'
    : layout.count === 1
      ? 'block'
      : 'none'
}

function resetCustomizer() {
  selectedLayout = '1-single'
  selectedPhotos = [null]
  activePhotoSlot = 0
  $('#photoUpload').value = ''
  $('#customizerError').textContent = ''
  renderLayoutOptions()
  renderPhotoSlots()
  renderCollagePreview()
}

function showOrderSuccess(orderNumber, paymentMethod) {
  $('#successMessage').textContent =
    paymentMethod === 'cod'
      ? `Order ${orderNumber} is confirmed. Pay when it arrives, and we’ll email you your order updates.`
      : `Order ${orderNumber} is paid and confirmed. We’ll email you your order updates.`
  setModal($('#successModal'), true)
}

function renderCheckout() {
  $('#checkoutItems').innerHTML = cart
    .map(
      (item) =>
        `<div class="summary-row"><div><b>${item.name}</b><small>${item.type === 'custom' ? `${item.size.replace('x', ' × ')} in · ${item.color}` : 'Ready-to-style frame'}</small></div><strong>${formatPrice(item.price * item.quantity)}</strong></div>`,
    )
    .join('')
  $('#checkoutTotal').textContent = formatPrice(cartTotal())
}

function setAuthMode(mode) {
  const registering = mode === 'register'
  $('#authForm').dataset.mode = mode
  $('#authNameField').hidden = !registering
  $('#authName').required = registering
  $('#authPassword').autocomplete = registering
    ? 'new-password'
    : 'current-password'
  $('#authTitle').textContent = registering
    ? 'Make a place for your memories.'
    : 'Welcome back.'
  $('#authIntro').textContent = registering
    ? 'Create an account to save every Photosite order in one place.'
    : 'Sign in to see your orders and check out faster.'
  $('#authSubmit').innerHTML = registering
    ? 'Create account <span aria-hidden="true">→</span>'
    : 'Sign in <span aria-hidden="true">→</span>'
  $('#authSwitch').innerHTML = registering
    ? 'Already have an account? <button type="button" id="authToggle">Sign in</button>'
    : 'New to Photosite? <button type="button" id="authToggle">Create an account</button>'
  $('#authToggle').addEventListener('click', () =>
    setAuthMode(registering ? 'login' : 'register'),
  )
  $('#authError').textContent = ''
}

function openAuth(mode = 'login') {
  setAuthMode(mode)
  setModal($('#authModal'), true)
}

function updateAccountLink() {
  const link = $('#accountLink')
  if (!link) return
  link.textContent = currentUser ? 'My account' : 'Sign in'
  link.dataset.guest = currentUser ? 'false' : 'true'
}

async function submitAuth(event) {
  event.preventDefault()
  const form = event.currentTarget
  const mode = form.dataset.mode || 'login'
  const error = $('#authError')
  const button = $('#authSubmit')
  error.textContent = ''
  button.disabled = true
  try {
    const body = {
      email: $('#authEmail').value,
      password: $('#authPassword').value,
    }
    if (mode === 'register') body.name = $('#authName').value
    const response = await fetch(
      `/api/auth/${mode === 'register' ? 'register' : 'login'}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    const data = await parseJsonResponse(response)
    if (!response.ok)
      throw new Error(data.error || 'We could not complete that request.')
    currentUser = data.user
    updateAccountLink()
    form.reset()
    setModal($('#authModal'), false)
  } catch (err) {
    error.textContent = err.message
  } finally {
    button.disabled = false
  }
}

async function submitOrder(event) {
  event.preventDefault()

  const button = $('#placeOrder')
  const error = $('#checkoutError')
  error.textContent = ''

  const form = event.currentTarget
  const formData = new FormData(form)
  const paymentMethod = formData.get('payment_method')

  const payloadItems = cart.map((item) => {
    if (item.type !== 'custom') {
      return {
        type: 'product',
        product_id: item.product_id,
        quantity: item.quantity,
      }
    }

    return {
      type: 'custom',
      size: item.size,
      color: item.color,
      purpose: item.purpose,
      quantity: item.quantity,
      collage_layout: item.collageLayout || '1-single',
      photo_count: item.files ? item.files.length : 0,
    }
  })

  formData.append('items', JSON.stringify(payloadItems))

  const customItem = cart.find((item) => item.type === 'custom')
  if (customItem?.files?.length) {
    customItem.files.forEach((file) => formData.append('photos', file))
  }

  button.disabled = true
  button.textContent =
    paymentMethod === 'razorpay' ? 'Opening payment…' : 'Placing order…'

  try {
    const response = await fetch('/api/orders', {
      method: 'POST',
      body: formData,
    })
    const data = await parseJsonResponse(response)

    if (!response.ok) {
      throw new Error(
        data.error || 'We couldn’t place the order. Please try again.',
      )
    }

    if (paymentMethod === 'razorpay') {
      openRazorpay(data)
      return
    }

    cart = []
    renderCart()
    setModal($('#checkoutModal'), false)
    showOrderSuccess(data.order_number, 'cod')
  } catch (err) {
    error.textContent = err.message
    button.disabled = false
    button.innerHTML = 'Place order <span aria-hidden="true">→</span>'
  }
}

function openRazorpay(order) {
  if (!window.Razorpay) {
    $('#checkoutError').textContent =
      'The payment window could not load. Please choose Cash on Delivery or try again.'
    $('#placeOrder').disabled = false
    return
  }
  const options = {
    key: order.razorpay.key,
    amount: order.amount * 100,
    currency: 'INR',
    name: order.razorpay.name,
    description: order.razorpay.description,
    order_id: order.razorpay.order_id,
    prefill: {
      name: $('#name').value,
      email: $('#email').value,
      contact: $('#phone').value,
    },
    theme: { color: '#fa714b' },
    handler: async (response) => {
      const verify = await fetch('/api/payments/razorpay/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(response),
      })
      const result = await parseJsonResponse(verify)
      if (!verify.ok) {
        $('#checkoutError').textContent =
          result.error ||
          'Payment verification failed. Please contact us with your payment ID.'
        return
      }
      cart = []
      renderCart()
      setModal($('#checkoutModal'), false)
      showOrderSuccess(result.order_number, 'razorpay')
    },
    modal: {
      ondismiss: () => {
        $('#placeOrder').disabled = false
        $('#placeOrder').innerHTML =
          'Place order <span aria-hidden="true">→</span>'
      },
    },
  }
  new Razorpay(options).open()
}

function setupCarousel() {
  const carousel = $('#carousel')
  let index = 0
  const update = () => {
    const card = carousel.querySelector('.product')
    const visible = window.innerWidth > 560 ? 3 : 1
    const max = Math.max(0, carousel.children.length - visible)
    index = Math.min(index, max)
    carousel.style.transform = `translateX(${-index * (card.getBoundingClientRect().width + 18)}px)`
  }
  $('#next').addEventListener('click', () => {
    index = (index + 1) % (window.innerWidth > 560 ? 2 : 4)
    update()
  })
  $('#prev').addEventListener('click', () => {
    const max = window.innerWidth > 560 ? 1 : 3
    index = (index - 1 + max + 1) % (max + 1)
    update()
  })
  window.addEventListener('resize', update)
  setInterval(() => {
    index = (index + 1) % (window.innerWidth > 560 ? 2 : 4)
    update()
  }, 5500)
}

function setupFrameGallery() {
  const track = $('#frameGalleryTrack')
  const previousButton = $('#frameGalleryPrev')
  const nextButton = $('#frameGalleryNext')
  const dotsContainer = $('#frameGalleryDots')

  if (!track || !previousButton || !nextButton || !dotsContainer) {
    return
  }

  const cards = [...track.querySelectorAll('.frame-gallery-card')]
  if (!cards.length) return

  let index = 0
  let timer = null
  let isHovered = false

  function getVisibleCount() {
    if (window.innerWidth <= 560) return 1
    if (window.innerWidth <= 900) return 2
    return 3
  }

  function getMaxIndex() {
    return Math.max(0, cards.length - getVisibleCount())
  }

  function renderDots() {
    const maxIndex = getMaxIndex()

    dotsContainer.innerHTML = Array.from(
      { length: maxIndex + 1 },
      (_, dotIndex) => `
        <button
          type="button"
          class="frame-gallery-dot ${dotIndex === index ? 'active' : ''}"
          aria-label="Show gallery position ${dotIndex + 1}"
          aria-current="${dotIndex === index ? 'true' : 'false'}"
          data-gallery-index="${dotIndex}">
        </button>
      `,
    ).join('')

    dotsContainer.querySelectorAll('[data-gallery-index]').forEach((dot) => {
      dot.addEventListener('click', () => {
        index = Number(dot.dataset.galleryIndex)
        updateGallery()
        restartTimer()
      })
    })
  }

  function updateGallery() {
    index = Math.min(index, getMaxIndex())

    const cardWidth = cards[0].getBoundingClientRect().width
    const gap = parseFloat(getComputedStyle(track).gap) || 0

    track.style.transform = `translateX(-${index * (cardWidth + gap)}px)`

    dotsContainer.querySelectorAll('.frame-gallery-dot').forEach((dot, i) => {
      dot.classList.toggle('active', i === index)
      dot.setAttribute('aria-current', i === index ? 'true' : 'false')
    })
  }

  function moveNext() {
    index = index >= getMaxIndex() ? 0 : index + 1
    updateGallery()
  }

  function movePrevious() {
    index = index <= 0 ? getMaxIndex() : index - 1
    updateGallery()
  }

  function stopTimer() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function startTimer() {
    stopTimer()

    if (
      isHovered ||
      document.hidden ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      getMaxIndex() === 0
    ) {
      return
    }

    timer = setInterval(moveNext, 4500)
  }

  function restartTimer() {
    startTimer()
  }

  previousButton.addEventListener('click', () => {
    movePrevious()
    restartTimer()
  })

  nextButton.addEventListener('click', () => {
    moveNext()
    restartTimer()
  })

  track.addEventListener('mouseenter', () => {
    isHovered = true
    stopTimer()
  })

  track.addEventListener('mouseleave', () => {
    isHovered = false
    startTimer()
  })

  track.addEventListener('focusin', stopTimer)

  track.addEventListener('focusout', (event) => {
    if (!track.contains(event.relatedTarget)) {
      startTimer()
    }
  })

  document.addEventListener('visibilitychange', startTimer)

  window.addEventListener('resize', () => {
    index = Math.min(index, getMaxIndex())
    renderDots()
    updateGallery()
    startTimer()
  })

  renderDots()
  updateGallery()
  startTimer()
}

function setupTestimonials() {
  const notes = [
    [
      'It’s become my favourite corner of the house. Looking at it just brings me right back to that day.',
      'Aanya Mehta',
      'Mumbai · The Heritage frame',
      'https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=140&q=80',
    ],
    [
      'The frame arrived beautifully packed, and the print is even more vivid than I imagined.',
      'Rohan Kapoor',
      'Bengaluru · The Gallery frame',
      'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=140&q=80',
    ],
    [
      'I gifted one to my parents and there were happy tears before the ribbon even hit the floor.',
      'Naina Shah',
      'Pune · The Everyday frame',
      'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=140&q=80',
    ],
  ]
  let index = 0
  setInterval(() => {
    index = (index + 1) % notes.length
    const [quote, name, detail, image] = notes[index]
    $('#quoteText').textContent = quote
    $('#personName').textContent = name
    $('#personDetail').textContent = detail
    $('#personImage').src = image
  }, 6500)
}

async function init() {
  try {
    ;[publicConfig, { user: currentUser }] = await Promise.all([
      fetch('/api/config').then((response) => response.json()),
      fetch('/api/auth/me').then((response) => response.json()),
    ])
  } catch {
    /* COD remains available if offline. */
  }
  updateAccountLink()
  if (!publicConfig.online_payments) {
    $('#razorpayOption').classList.add('disabled')
    $('#razorpayOption input').disabled = true
    $('#razorpayOption').title =
      'Online payments will be available when Razorpay is configured.'
  }
  renderCart()
  setupCarousel()
  setupFrameGallery()
  setupTestimonials()
  renderLayoutOptions()
  renderPhotoSlots()
  renderCollagePreview()
  $$('.open-customizer').forEach((button) =>
    button.addEventListener('click', (event) => {
      event.preventDefault()
      resetCustomizer()
      setModal($('#customizer'), true)
    }),
  )
  $('#modalClose').addEventListener('click', () =>
    setModal($('#customizer'), false),
  )
  $('#checkoutClose').addEventListener('click', () =>
    setModal($('#checkoutModal'), false),
  )
  $('#successClose').addEventListener('click', () =>
    setModal($('#successModal'), false),
  )
  $$('.modal').forEach((modal) =>
    modal.addEventListener('click', (event) => {
      if (event.target === modal) setModal(modal, false)
    }),
  )
  $('#cartButton').addEventListener('click', openCart)
  $('#closeCart').addEventListener('click', closeCart)
  $('#drawerBackdrop').addEventListener('click', closeCart)
  $('#checkoutButton').addEventListener('click', () => {
    if (!cart.length) return
    closeCart()
    renderCheckout()
    if (currentUser) {
      $('#name').value = currentUser.name
      $('#email').value = currentUser.email
    }
    setModal($('#checkoutModal'), true)
  })
  $('#accountLink').addEventListener('click', (event) => {
    if ($('#accountLink').dataset.guest === 'true') {
      event.preventDefault()
      openAuth()
    }
  })
  $('#authClose').addEventListener('click', () =>
    setModal($('#authModal'), false),
  )
  $('#authForm').addEventListener('submit', submitAuth)
  $$('.swatch').forEach((swatch) =>
    swatch.addEventListener('click', () => {
      selectedColor = swatch.dataset.color
      $$('.swatch').forEach((item) => item.classList.remove('active'))
      swatch.classList.add('active')
      const colors = {
        walnut: ['#a26344', '#6d3d28'],
        oak: ['#e4ded0', '#42453f'],
        charcoal: ['#3e413d', '#242624'],
        brass: ['#c48a3f', '#79501e'],
      }
      $('#previewFrame').style.background = colors[selectedColor][0]
      $('#previewFrame').style.borderColor = colors[selectedColor][1]
    }),
  )
  $('#size').addEventListener('change', updateCustomPrice)

  $('#photoUpload').addEventListener('change', (event) => {
    const file = event.target.files[0]
    if (!file) return

    if (file.size > 8 * 1024 * 1024) {
      event.target.value = ''
      alert('Please upload a photo under 8 MB.')
      return
    }

    selectedPhotos[activePhotoSlot] = file
    renderPhotoSlots()
    renderCollagePreview()
  })

  $('#customFrameForm').addEventListener('submit', (event) => {
    event.preventDefault()

    const layout = selectedLayoutData()
    const files = selectedPhotos.filter(Boolean)
    const customizerError = $('#customizerError')

    customizerError.textContent = ''

    if (files.length !== layout.count) {
      customizerError.textContent = `Please add all ${layout.count} photo${layout.count === 1 ? '' : 's'} for this layout.`
      return
    }

    const size = $('#size').value

    addToCart({
      type: 'custom',
      name:
        layout.count === 1
          ? 'Custom photo frame'
          : `Custom ${layout.count}-photo collage`,
      size,
      color: selectedColor,
      purpose: $('#purpose').value,
      price: framePrices[size],
      files,
      collageLayout: selectedLayout,
      preview: files[0] ? URL.createObjectURL(files[0]) : null,
    })

    resetCustomizer()
    setModal($('#customizer'), false)
  })
  $$('.add-product').forEach((button) =>
    button.addEventListener('click', () => {
      const product = productData[button.dataset.product]
      addToCart({
        type: 'product',
        product_id: button.dataset.product,
        name: product.name,
        price: product.price,
      })
    }),
  )
  $('#checkoutForm').addEventListener('submit', submitOrder)
  $('#menuButton').addEventListener('click', () => {
    const links = $('#navLinks')
    links.style.display = links.style.display === 'flex' ? 'none' : 'flex'
  })
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      $$('.modal.open').forEach((modal) => setModal(modal, false))
      closeCart()
    }
  })
  if (new URLSearchParams(window.location.search).get('signin') === '1')
    openAuth()
}
document.addEventListener('DOMContentLoaded', init)
